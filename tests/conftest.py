import os
from collections.abc import AsyncGenerator, Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("DATABASE_URL_TEST", "sqlite+aiosqlite:///./.pytest-e-bank.db"),
)
os.environ["OIDC_ENABLED"] = "false"
os.environ.setdefault("LEGACY_CHALLENGE_ROUTES", "true")
os.environ.setdefault("IDEMPOTENCY_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from app.core.config import get_settings

get_settings.cache_clear()

from app.core import database as app_db  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402, F401
    Account,
    Consent,
    DemoGrant,
    Holder,
    JournalEntry,
    LedgerAccount,
    LedgerPosting,
    OnboardingDocument,
    OnboardingSession,
    Transaction,
    User,
)
from app.repositories.account_repository import AccountRepository  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# NullPool avoids reusing async connections across TestClient / pytest event loops.
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=not TEST_DATABASE_URL.startswith("sqlite"),
    poolclass=NullPool,
    connect_args=(
        {"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {}
    ),
)

TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def _dispose_engines() -> None:
    await test_engine.dispose()
    await app_db.engine.dispose()


async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = _get_test_db


@pytest.fixture(autouse=True)
async def clean_db() -> AsyncGenerator[None, None]:
    """Reset DB and dispose engines so TestClient can bind a fresh event loop."""
    await _dispose_engines()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        repo = AccountRepository(session)
        await repo.delete_all()
        await session.commit()
    await _dispose_engines()
    yield
    await _dispose_engines()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


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
