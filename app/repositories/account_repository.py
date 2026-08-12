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
    account_number: int | None = None
    digit: int | None = None
    onboarding_status: str = "not_started"

    @property
    def display_number(self) -> str | None:
        if self.account_number is None or self.digit is None:
            return None
        return f"{int(self.account_number)}-{int(self.digit)}"


@dataclass(frozen=True)
class TransactionRecord:
    id: str
    internal_id: int
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
        balance = await self._balance_for(account)
        return self._to_record(account, balance)

    async def get_for_update(self, account_id: str) -> AccountRecord | None:
        account = await self._lock_account(account_id)
        if account is None:
            return None
        balance = await self._balance_for(account)
        return self._to_record(account, balance)

    async def get_by_owner_kind(
        self,
        owner_subject: str,
        kind: str = "checking",
    ) -> AccountRecord | None:
        """Return the oldest active-or-any checking account for the owner."""
        result = await self._session.execute(
            select(Account)
            .where(
                Account.owner_subject == owner_subject,
                Account.kind == kind,
            )
            .order_by(
                Account.account_number.asc().nulls_last(),
                Account.created_at.asc(),
                Account.id.asc(),
            )
            .limit(1),
        )
        account = result.scalar_one_or_none()
        if account is None:
            return None
        balance = await self._balance_for(account)
        return self._to_record(account, balance)

    async def list_by_owner_kind(
        self,
        owner_subject: str,
        kind: str = "checking",
    ) -> list[AccountRecord]:
        result = await self._session.execute(
            select(Account)
            .where(
                Account.owner_subject == owner_subject,
                Account.kind == kind,
            )
            .order_by(
                Account.account_number.asc().nulls_last(),
                Account.created_at.asc(),
                Account.id.asc(),
            ),
        )
        rows = list(result.scalars().all())
        out: list[AccountRecord] = []
        for account in rows:
            balance = await self._balance_for(account)
            out.append(self._to_record(account, balance))
        return out

    async def count_by_owner_kind(
        self,
        owner_subject: str,
        kind: str = "checking",
    ) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Account)
            .where(
                Account.owner_subject == owner_subject,
                Account.kind == kind,
            ),
        )
        return int(result.scalar_one())

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
        if account is not None:
            account.balance_cached = Decimal(str(account.balance_cached or 0)) + amount
            await self._session.flush()
        balance = await self._sum_balance(account_id)
        if account is None:
            return AccountRecord(id=account_id, balance=balance)
        return self._to_record(account, Decimal(str(account.balance_cached or balance)))

    async def get_transaction_by_public_id(
        self,
        public_id: str,
    ) -> TransactionRecord | None:
        result = await self._session.execute(
            select(Transaction).where(Transaction.public_id == public_id),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_tx_record(row)

    async def get_many(self, account_ids: list[str]) -> dict[str, AccountRecord]:
        if not account_ids:
            return {}
        result = await self._session.execute(
            select(Account).where(Account.id.in_(account_ids)),
        )
        out: dict[str, AccountRecord] = {}
        for account in result.scalars().all():
            balance = await self._balance_for(account)
            out[account.id] = self._to_record(account, balance)
        return out

    async def sum_amount_before(
        self,
        account_id: str,
        *,
        before,
    ) -> Decimal:
        """Sum ledger amounts strictly before `before` (opening balance helper)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.account_id == account_id,
                Transaction.created_at < before,
            ),
        )
        return Decimal(str(result.scalar_one()))

    async def list_transactions(
        self,
        account_id: str,
        *,
        limit: int = 20,
        before_public_id: str | None = None,
        created_from=None,
        created_to=None,
        types: list[str] | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        direction: str | None = None,
        chronological: bool = False,
    ) -> list[TransactionRecord]:
        before_id: int | None = None
        if before_public_id:
            cursor_row = await self._session.execute(
                select(Transaction.id).where(
                    Transaction.public_id == before_public_id,
                    Transaction.account_id == account_id,
                ),
            )
            before_id = cursor_row.scalar_one_or_none()
            if before_id is None:
                return []
        stmt = select(Transaction).where(Transaction.account_id == account_id)
        if before_id is not None:
            stmt = stmt.where(Transaction.id < before_id)
        if created_from is not None:
            stmt = stmt.where(Transaction.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(Transaction.created_at < created_to)
        if types:
            stmt = stmt.where(Transaction.type.in_(types))
        if min_amount is not None:
            stmt = stmt.where(Transaction.amount >= min_amount)
        if max_amount is not None:
            stmt = stmt.where(Transaction.amount <= max_amount)
        if direction == "in":
            stmt = stmt.where(Transaction.amount >= 0)
        elif direction == "out":
            stmt = stmt.where(Transaction.amount < 0)
        if chronological:
            stmt = stmt.order_by(Transaction.id.asc())
        else:
            stmt = stmt.order_by(Transaction.id.desc())
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_tx_record(row) for row in rows]

    @staticmethod
    def _to_tx_record(row: Transaction) -> TransactionRecord:
        return TransactionRecord(
            id=row.public_id,
            internal_id=row.id,
            account_id=row.account_id,
            amount=row.amount,
            type=row.type,
            counterparty_account_id=row.counterparty_account_id,
            memo=row.memo,
            created_at=row.created_at,
        )

    async def delete_all(self) -> None:
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await self._session.execute(
                text(
                    "TRUNCATE TABLE ledger_postings, journal_entries, ledger_accounts, "
                    "holders, onboarding_documents, onboarding_sessions, "
                    "consents, demo_grants, transactions, accounts, users "
                    "RESTART IDENTITY CASCADE"
                ),
            )
            await self._session.execute(
                text(
                    "INSERT INTO ledger_accounts (id, code, name, kind) VALUES "
                    "('sys_cash', 'cash', 'System cash', 'asset') "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
        else:
            from app.models.holder import Holder
            from app.models.ledger import JournalEntry, LedgerAccount, LedgerPosting
            from app.models.onboarding import (
                Consent,
                DemoGrant,
                OnboardingDocument,
                OnboardingSession,
            )
            from app.models.user import User

            await self._session.execute(delete(LedgerPosting))
            await self._session.execute(delete(JournalEntry))
            await self._session.execute(delete(LedgerAccount))
            await self._session.execute(delete(Holder))
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

    async def _balance_for(self, account: Account) -> Decimal:
        cached = getattr(account, "balance_cached", None)
        if cached is not None:
            return Decimal(str(cached))
        return await self._sum_balance(account.id)

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
            account_number=account.account_number,
            digit=account.digit,
            onboarding_status=account.onboarding_status,
        )
