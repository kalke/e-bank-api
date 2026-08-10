"""Append-only double-entry ledger."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.domain.ids import new_uuid
from app.errors import DomainError, InsufficientFunds
from app.models.account import Account
from app.models.ledger import JournalEntry, LedgerAccount, LedgerPosting
from app.models.transaction import Transaction

logger = get_logger(__name__)

SYS_CASH_ID = "sys_cash"


class LedgerError(DomainError):
    status_code = 400


class IdempotentReplay(Exception):
    def __init__(self, journal_id: str, payload: dict):
        self.journal_id = journal_id
        self.payload = payload
        super().__init__(journal_id)


@dataclass(frozen=True)
class PostingLine:
    ledger_account_id: str
    side: str  # debit | credit
    amount: Decimal


class LedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_system_accounts(self) -> None:
        existing = await self._session.get(LedgerAccount, SYS_CASH_ID)
        if existing is None:
            self._session.add(
                LedgerAccount(
                    id=SYS_CASH_ID,
                    code="cash",
                    name="System cash",
                    kind="asset",
                )
            )
            await self._session.flush()

    async def ensure_customer_ledger_account(self, account: Account) -> None:
        await self.ensure_system_accounts()
        existing = await self._session.get(LedgerAccount, account.id)
        if existing is None:
            self._session.add(
                LedgerAccount(
                    id=account.id,
                    code=f"customer:{account.id}",
                    name=f"Customer {account.display_number or account.id}",
                    kind="liability",
                )
            )
            await self._session.flush()

    async def customer_balance(self, account_id: str) -> Decimal:
        credits = func.coalesce(
            func.sum(
                case(
                    (LedgerPosting.side == "credit", LedgerPosting.amount),
                    else_=0,
                )
            ),
            0,
        )
        debits = func.coalesce(
            func.sum(
                case(
                    (LedgerPosting.side == "debit", LedgerPosting.amount),
                    else_=0,
                )
            ),
            0,
        )
        result = await self._session.execute(
            select(credits - debits).where(
                LedgerPosting.ledger_account_id == account_id
            )
        )
        return Decimal(str(result.scalar_one()))

    async def post(
        self,
        *,
        entry_type: str,
        lines: list[PostingLine],
        actor_subject: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        reason: str | None = None,
        mirror_transactions: bool = True,
    ) -> JournalEntry:
        if idempotency_key:
            existing = await self._session.execute(
                select(JournalEntry).where(
                    JournalEntry.idempotency_key == idempotency_key
                )
            )
            found = existing.scalar_one_or_none()
            if found is not None:
                raise IdempotentReplay(found.id, {"journal_id": found.id})

        if len(lines) < 2:
            raise LedgerError("journal requires at least two postings")
        debit_total = sum(
            (line.amount for line in lines if line.side == "debit"), Decimal("0")
        )
        credit_total = sum(
            (line.amount for line in lines if line.side == "credit"), Decimal("0")
        )
        if debit_total != credit_total:
            raise LedgerError("journal is not balanced")
        if debit_total <= 0:
            raise LedgerError("journal amount must be positive")
        for line in lines:
            if line.side not in {"debit", "credit"}:
                raise LedgerError("invalid posting side")
            if line.amount <= 0:
                raise LedgerError("posting amount must be positive")

        journal = JournalEntry(
            id=new_uuid(),
            actor_subject=actor_subject,
            request_id=request_id,
            idempotency_key=idempotency_key,
            source_ip=source_ip,
            user_agent=user_agent,
            entry_type=entry_type,
            reason=reason,
        )
        self._session.add(journal)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if idempotency_key:
                existing = await self._session.execute(
                    select(JournalEntry).where(
                        JournalEntry.idempotency_key == idempotency_key
                    )
                )
                found = existing.scalar_one_or_none()
                if found is not None:
                    raise IdempotentReplay(found.id, {"journal_id": found.id}) from exc
            raise

        for line in lines:
            self._session.add(
                LedgerPosting(
                    journal_id=journal.id,
                    ledger_account_id=line.ledger_account_id,
                    side=line.side,
                    amount=line.amount,
                )
            )
        await self._session.flush()

        # Keep customer checking balance_cached + legacy transactions in sync
        for line in lines:
            if line.ledger_account_id == SYS_CASH_ID:
                continue
            account = await self._session.get(Account, line.ledger_account_id)
            if account is None:
                continue
            delta = line.amount if line.side == "credit" else -line.amount
            account.balance_cached = Decimal(str(account.balance_cached or 0)) + delta
            if mirror_transactions:
                txn_type = {
                    "welcome_grant": "demo_grant",
                    "transfer": (
                        "transfer_out" if line.side == "debit" else "transfer_in"
                    ),
                    "withdraw": "withdraw",
                }.get(entry_type, entry_type)
                counterparty = None
                if entry_type == "transfer":
                    for other in lines:
                        if (
                            other.ledger_account_id != line.ledger_account_id
                            and other.ledger_account_id != SYS_CASH_ID
                        ):
                            counterparty = other.ledger_account_id
                            break
                self._session.add(
                    Transaction(
                        account_id=account.id,
                        amount=delta,
                        type=txn_type,
                        counterparty_account_id=counterparty,
                        actor_subject=actor_subject,
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                        memo=reason,
                    )
                )
        await self._session.flush()
        logger.info(
            "ledger_journal_posted",
            journal_id=journal.id,
            entry_type=entry_type,
            amount=str(debit_total),
        )
        return journal

    async def welcome_grant(
        self,
        account: Account,
        amount: Decimal,
        **audit: object,
    ) -> JournalEntry:
        await self.ensure_customer_ledger_account(account)
        return await self.post(
            entry_type="welcome_grant",
            lines=[
                PostingLine(SYS_CASH_ID, "debit", amount),
                PostingLine(account.id, "credit", amount),
            ],
            reason="Welcome demo funds",
            **audit,  # type: ignore[arg-type]
        )

    async def transfer(
        self,
        origin: Account,
        destination: Account,
        amount: Decimal,
        **audit: object,
    ) -> JournalEntry:
        await self.ensure_customer_ledger_account(origin)
        await self.ensure_customer_ledger_account(destination)
        balance = Decimal(str(origin.balance_cached or 0))
        if balance - amount < Decimal(str(origin.overdraft_limit or 0)):
            raise InsufficientFunds(origin.id)
        return await self.post(
            entry_type="transfer",
            lines=[
                PostingLine(origin.id, "debit", amount),
                PostingLine(destination.id, "credit", amount),
            ],
            **audit,  # type: ignore[arg-type]
        )

    async def withdraw(
        self,
        account: Account,
        amount: Decimal,
        **audit: object,
    ) -> JournalEntry:
        await self.ensure_customer_ledger_account(account)
        balance = Decimal(str(account.balance_cached or 0))
        if balance - amount < Decimal(str(account.overdraft_limit or 0)):
            raise InsufficientFunds(account.id)
        return await self.post(
            entry_type="withdraw",
            lines=[
                PostingLine(account.id, "debit", amount),
                PostingLine(SYS_CASH_ID, "credit", amount),
            ],
            reason="Demo ATM withdraw",
            **audit,  # type: ignore[arg-type]
        )
