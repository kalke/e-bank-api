import asyncio
import os
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("DATABASE_URL_TEST", "sqlite+aiosqlite:///:memory:"),
)

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.account_repository import AccountRepository  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

if TEST_DATABASE_URL.startswith("sqlite"):
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    test_engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)

TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def _create_tables() -> None:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(_create_tables())


async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = _get_test_db


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
async def account_repo(db_session: AsyncSession) -> AccountRepository:
    return AccountRepository(db_session)


@pytest.fixture
async def service(account_repo: AccountRepository):
    from app.services import AccountService

    return AccountService(account_repo)


@pytest.fixture(autouse=True)
async def clean_db() -> AsyncGenerator[None, None]:
    async with TestSessionLocal() as session:
        repo = AccountRepository(session)
        await repo.delete_all()
        await session.commit()
    yield


async def set_account_balance(
    repo: AccountRepository,
    account_id: str,
    balance: int,
) -> None:
    account = await repo.get(account_id)
    if account is None:
        await repo.create(account_id, Decimal(balance))
        return

    delta = Decimal(balance) - account.balance
    if delta != 0:
        txn_type = "deposit" if delta > 0 else "withdraw"
        await repo.record_transaction(account_id, delta, txn_type)


@pytest.fixture
async def set_balance(account_repo: AccountRepository):
    async def _set(account_id: str, balance: int) -> None:
        await set_account_balance(account_repo, account_id, balance)

    return _set
