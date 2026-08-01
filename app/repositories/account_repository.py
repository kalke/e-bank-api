from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction


@dataclass(frozen=True)
class AccountRecord:
    id: str
    balance: Decimal


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> AccountRecord | None:
        account = await self._get_account_row(account_id)
        if account is None:
            return None
        balance = await self._sum_balance(account_id)
        return AccountRecord(id=account_id, balance=balance)

    async def get_for_update(self, account_id: str) -> AccountRecord | None:
        account = await self._lock_account(account_id)
        if account is None:
            return None
        balance = await self._sum_balance(account_id)
        return AccountRecord(id=account_id, balance=balance)

    async def ensure_account(self, account_id: str) -> None:
        if await self._get_account_row(account_id) is None:
            self._session.add(Account(id=account_id))
            await self._session.flush()

    async def lock_accounts_for_update(self, *account_ids: str) -> None:
        for account_id in sorted(set(account_ids)):
            await self._lock_account(account_id)

    async def create(self, account_id: str, initial_balance: Decimal) -> AccountRecord:
        self._session.add(Account(id=account_id))
        await self._session.flush()
        if initial_balance != 0:
            return await self.record_transaction(
                account_id,
                initial_balance,
                "deposit",
            )
        return AccountRecord(id=account_id, balance=Decimal(0))

    async def record_transaction(
        self,
        account_id: str,
        amount: Decimal,
        txn_type: str,
        counterparty_account_id: str | None = None,
    ) -> AccountRecord:
        self._session.add(
            Transaction(
                account_id=account_id,
                amount=amount,
                type=txn_type,
                counterparty_account_id=counterparty_account_id,
            ),
        )
        await self._session.flush()
        balance = await self._sum_balance(account_id)
        return AccountRecord(id=account_id, balance=balance)

    async def delete_all(self) -> None:
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await self._session.execute(
                text("TRUNCATE TABLE transactions, accounts RESTART IDENTITY CASCADE"),
            )
        else:
            await self._session.execute(delete(Transaction))
            await self._session.execute(delete(Account))
        await self._session.flush()

    async def _get_account_row(self, account_id: str) -> Account | None:
        result = await self._session.execute(
            select(Account).where(Account.id == account_id),
        )
        return result.scalar_one_or_none()

    async def _lock_account(self, account_id: str) -> Account | None:
        result = await self._session.execute(
            select(Account).where(Account.id == account_id).with_for_update(),
        )
        return result.scalar_one_or_none()

    async def _sum_balance(self, account_id: str) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.account_id == account_id,
            ),
        )
        total = result.scalar_one()
        return Decimal(str(total))
