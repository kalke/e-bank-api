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
    owner_subject: str | None = None
    kind: str = "checking"
    currency: str = "USD"
    status: str = "active"
    overdraft_limit: Decimal = Decimal("0")


@dataclass(frozen=True)
class TransactionRecord:
    id: int
    account_id: str
    amount: Decimal
    type: str
    counterparty_account_id: str | None
    memo: str | None
    created_at: object


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> AccountRecord | None:
        account = await self._get_account_row(account_id)
        if account is None:
            return None
        balance = await self._sum_balance(account_id)
        return self._to_record(account, balance)

    async def get_for_update(self, account_id: str) -> AccountRecord | None:
        account = await self._lock_account(account_id)
        if account is None:
            return None
        balance = await self._sum_balance(account_id)
        return self._to_record(account, balance)

    async def get_by_owner_kind(
        self,
        owner_subject: str,
        kind: str = "checking",
    ) -> AccountRecord | None:
        result = await self._session.execute(
            select(Account).where(
                Account.owner_subject == owner_subject,
                Account.kind == kind,
            ),
        )
        account = result.scalar_one_or_none()
        if account is None:
            return None
        balance = await self._sum_balance(account.id)
        return self._to_record(account, balance)

    async def ensure_account(
        self,
        account_id: str,
        *,
        owner_subject: str | None = None,
        kind: str = "checking",
        currency: str = "USD",
        overdraft_limit: Decimal = Decimal("0"),
    ) -> None:
        if await self._get_account_row(account_id) is None:
            self._session.add(
                Account(
                    id=account_id,
                    owner_subject=owner_subject,
                    kind=kind,
                    currency=currency,
                    overdraft_limit=overdraft_limit,
                ),
            )
            await self._session.flush()

    async def lock_accounts_for_update(self, *account_ids: str) -> None:
        for account_id in sorted(set(account_ids)):
            await self._lock_account(account_id)

    async def create(
        self,
        account_id: str,
        initial_balance: Decimal,
        *,
        owner_subject: str | None = None,
        kind: str = "checking",
        currency: str = "USD",
        overdraft_limit: Decimal = Decimal("0"),
        actor_subject: str | None = None,
        request_id: str | None = None,
        txn_type: str = "deposit",
        memo: str | None = None,
    ) -> AccountRecord:
        self._session.add(
            Account(
                id=account_id,
                owner_subject=owner_subject,
                kind=kind,
                currency=currency,
                overdraft_limit=overdraft_limit,
            ),
        )
        await self._session.flush()
        if initial_balance != 0:
            return await self.record_transaction(
                account_id,
                initial_balance,
                txn_type,
                actor_subject=actor_subject,
                request_id=request_id,
                memo=memo,
            )
        return AccountRecord(
            id=account_id,
            balance=Decimal(0),
            owner_subject=owner_subject,
            kind=kind,
            currency=currency,
            overdraft_limit=overdraft_limit,
        )

    async def record_transaction(
        self,
        account_id: str,
        amount: Decimal,
        txn_type: str,
        counterparty_account_id: str | None = None,
        *,
        actor_subject: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        memo: str | None = None,
    ) -> AccountRecord:
        txn = Transaction(
            account_id=account_id,
            amount=amount,
            type=txn_type,
            counterparty_account_id=counterparty_account_id,
            actor_subject=actor_subject,
            request_id=request_id,
            idempotency_key=idempotency_key,
            memo=memo,
        )
        self._session.add(txn)
        await self._session.flush()
        account = await self._get_account_row(account_id)
        balance = await self._sum_balance(account_id)
        if account is None:
            return AccountRecord(id=account_id, balance=balance)
        return self._to_record(account, balance)

    async def list_transactions(
        self,
        account_id: str,
        *,
        limit: int = 20,
        before_id: int | None = None,
    ) -> list[TransactionRecord]:
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(Transaction.id < before_id)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [
            TransactionRecord(
                id=row.id,
                account_id=row.account_id,
                amount=row.amount,
                type=row.type,
                counterparty_account_id=row.counterparty_account_id,
                memo=row.memo,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def delete_all(self) -> None:
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await self._session.execute(
                text(
                    "TRUNCATE TABLE onboarding_documents, onboarding_sessions, "
                    "consents, demo_grants, transactions, accounts, users "
                    "RESTART IDENTITY CASCADE"
                ),
            )
        else:
            from app.models.onboarding import (
                Consent,
                DemoGrant,
                OnboardingDocument,
                OnboardingSession,
            )
            from app.models.user import User

            await self._session.execute(delete(OnboardingDocument))
            await self._session.execute(delete(OnboardingSession))
            await self._session.execute(delete(Consent))
            await self._session.execute(delete(DemoGrant))
            await self._session.execute(delete(Transaction))
            await self._session.execute(delete(Account))
            await self._session.execute(delete(User))
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

    @staticmethod
    def _to_record(account: Account, balance: Decimal) -> AccountRecord:
        return AccountRecord(
            id=account.id,
            balance=balance,
            owner_subject=account.owner_subject,
            kind=account.kind,
            currency=account.currency,
            status=account.status,
            overdraft_limit=Decimal(str(account.overdraft_limit or 0)),
        )
