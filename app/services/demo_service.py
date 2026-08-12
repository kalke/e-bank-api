from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.money import Money, parse_positive_money
from app.domain.validation import format_account_display, mask_document
from app.errors import (
    AccountNotFound,
    ForbiddenAccountAccess,
    OnboardingError,
    TransferLimitExceeded,
)
from app.models.account import Account
from app.models.holder import Holder
from app.repositories.account_repository import AccountRecord, AccountRepository
from app.repositories.user_repository import (
    DemoGrantRepository,
    OnboardingRepository,
    UserRepository,
)
from app.services.ledger import LedgerService
from app.services.statement_export import EXPORT_MAX_ROWS, build_statement_csv
from app.services.statement_pdf import build_receipt_pdf, build_statement_pdf
from app.services.statement_present import (
    CounterpartyContext,
    present_transaction,
    title_case_name,
    type_filter_match,
)
from app.services.statement_storage import BankPDFStore, receipt_key
from app.services.transfer import TransferService

logger = get_logger(__name__)


@dataclass(frozen=True)
class DemoAccountView:
    id: str
    balance: str
    currency: str
    kind: str
    status: str
    onboarding_status: str
    demo_credited: bool
    account_number: int | None = None
    digit: int | None = None
    display_number: str | None = None
    holder_name: str | None = None


class DemoBankService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AccountRepository(session)
        self._users = UserRepository(session)
        self._grants = DemoGrantRepository(session)
        self._onboarding = OnboardingRepository(session)
        self._settings = get_settings()
        self._transfers = TransferService(session)
        self._ledger = LedgerService(session)

    async def bootstrap(
        self,
        subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> DemoAccountView:
        """Deprecated free bootstrap — account opens via onboarding complete/skip."""
        _ = email, display_name, request_id
        user = await self._users.get(subject)
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if (
            account is not None
            and user
            and user.onboarding_status
            in {
                "completed",
                "skipped",
            }
        ):
            return await self.get_my_account(subject)
        raise OnboardingError("use onboarding complete or skip to open an account")

    async def get_my_account(self, subject: str) -> DemoAccountView:
        """Return the primary checking account even while onboarding is incomplete.

        Money-moving ops stay gated; listing/reading accounts must not hide
        existing rows when the user restarts KYC (`in_progress`).
        """
        user = await self._users.get(subject)
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if account is None:
            raise AccountNotFound("checking")
        holder = await self._session.get(Holder, subject)
        status = user.onboarding_status if user else "not_started"
        return self._view(
            account,
            status,
            demo_credited=user.demo_credited_at is not None if user else False,
            holder_name=holder.full_name if holder else None,
        )

    async def list_accounts(self, subject: str) -> list[DemoAccountView]:
        """List owned checking accounts regardless of onboarding gate."""
        user = await self._users.get(subject)
        rows = await self._accounts.list_by_owner_kind(subject, "checking")
        if not rows:
            return []
        holder = await self._session.get(Holder, subject)
        status = user.onboarding_status if user else "not_started"
        credited = user.demo_credited_at is not None if user else False
        return [
            self._view(
                row,
                status,
                demo_credited=credited,
                holder_name=holder.full_name if holder else None,
            )
            for row in rows
        ]

    async def open_additional_account(
        self,
        subject: str,
        *,
        request_id: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        idempotency_key: str | None = None,
    ) -> DemoAccountView:
        """Open another checking account for the same holder/CPF (demo transfers)."""
        user = await self._users.get(subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        holder = await self._session.get(Holder, subject)
        if holder is None:
            raise OnboardingError("complete onboarding before using the bank")

        limit = int(self._settings.max_checking_accounts_per_user)
        count = await self._accounts.count_by_owner_kind(subject, "checking")
        if count >= limit:
            raise OnboardingError(f"account limit reached ({limit})")

        from app.services.onboarding_complete import OnboardingCompletionService

        return await OnboardingCompletionService(self._session).open_extra_checking(
            subject,
            holder_name=holder.full_name,
            onboarding_status=user.onboarding_status,
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            idempotency_key=idempotency_key,
        )

    async def get_account_by_display(
        self,
        subject: str,
        display: str,
    ) -> DemoAccountView:
        user = await self._users.get(subject)
        rows = await self._accounts.list_by_owner_kind(subject, "checking")
        holder = await self._session.get(Holder, subject)
        status = user.onboarding_status if user else "not_started"
        credited = user.demo_credited_at is not None if user else False
        for row in rows:
            if row.display_number == display or row.id == display:
                return self._view(
                    row,
                    status,
                    demo_credited=credited,
                    holder_name=holder.full_name if holder else None,
                )
        raise ForbiddenAccountAccess(display)

    async def list_transactions(
        self,
        subject: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
        account_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        tx_type: str | None = None,
        direction: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
    ) -> list[dict]:
        account = await self._resolve_owned_checking(subject, account_id)
        created_from, created_to = self._parse_day_bounds(date_from, date_to)
        types = self._types_for_filter(tx_type)
        rows = await self._accounts.list_transactions(
            account.id,
            limit=min(limit, 100),
            before_public_id=cursor,
            created_from=created_from,
            created_to=created_to,
            types=types,
            min_amount=self._optional_decimal(min_amount),
            max_amount=self._optional_decimal(max_amount),
            direction=(direction or "").strip().lower() or None,
        )
        # Soft type aliases may need post-filter when SQL used exact types.
        if tx_type and types is None:
            rows = [r for r in rows if type_filter_match(r.type, tx_type)]
        return await self._present_rows(rows, currency=account.currency)

    async def get_transaction(self, subject: str, public_id: str) -> dict:
        row = await self._accounts.get_transaction_by_public_id(public_id)
        if row is None:
            raise AccountNotFound(public_id)
        account = await self._require_owned_account(subject, row.account_id)
        presented = (await self._present_rows([row], currency=account.currency))[0]
        parties = await self._parties_for(row, account)
        presented["parties"] = parties
        return presented

    async def get_receipt_pdf(
        self,
        subject: str,
        public_id: str,
    ) -> tuple[bytes, str]:
        detail = await self.get_transaction(subject, public_id)
        parties = detail.pop("parties", {})
        account_id = str(detail.get("account_id") or "")
        key = receipt_key(account_id, public_id)
        store = BankPDFStore()
        fields = {
            "tx_id": public_id,
            "account_id": account_id,
            "subject": subject,
            "s3_key": key,
        }

        if store.enabled:
            cached = store.get(key)
            if cached is not None:
                logger.info("bank.receipt.cache_hit", outcome="ok", **fields)
                filename = f"receipt-{detail.get('type') or 'tx'}-{public_id}.pdf"
                return cached, filename

        pdf = build_receipt_pdf(detail, parties=parties)
        if store.enabled:
            store.put(key, pdf)
        logger.info("bank.receipt.generated", outcome="ok", **fields)
        filename = f"receipt-{detail.get('type') or 'tx'}-{public_id}.pdf"
        return pdf, filename

    async def export_statement(
        self,
        subject: str,
        *,
        fmt: str,
        account_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        tx_type: str | None = None,
        direction: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
    ) -> tuple[bytes, str, str]:
        account = await self._resolve_owned_checking(subject, account_id)
        created_from, created_to = self._parse_day_bounds(date_from, date_to)
        types = self._types_for_filter(tx_type)
        rows = await self._accounts.list_transactions(
            account.id,
            limit=EXPORT_MAX_ROWS,
            created_from=created_from,
            created_to=created_to,
            types=types,
            min_amount=self._optional_decimal(min_amount),
            max_amount=self._optional_decimal(max_amount),
            direction=(direction or "").strip().lower() or None,
            chronological=True,
        )
        if tx_type and types is None:
            rows = [r for r in rows if type_filter_match(r.type, tx_type)]

        opening_dt = created_from
        if opening_dt is None and rows:
            first = rows[0].created_at
            opening_dt = first if isinstance(first, datetime) else None
        opening = (
            await self._accounts.sum_amount_before(account.id, before=opening_dt)
            if opening_dt is not None
            else Decimal("0")
        )
        running = Decimal(str(opening))
        presented: list[dict] = []
        cp_map = await self._counterparty_map(rows)
        for row in rows:
            item = present_transaction(
                tx_id=row.id,
                account_id=row.account_id,
                amount=row.amount,
                tx_type=row.type,
                counterparty_account_id=row.counterparty_account_id,
                memo=row.memo,
                created_at=row.created_at,
                currency=account.currency,
                counterparty=cp_map.get(row.counterparty_account_id or ""),
            )
            running += Decimal(str(row.amount))
            item["balance_after"] = Money(running).as_str()
            presented.append(item)

        holder = await self._session.get(Holder, subject)
        holder_name = title_case_name(holder.full_name if holder else None) or "—"
        display = account.display_number or account.id
        period = self._period_label(date_from, date_to)
        closing = Money(running).as_str()
        opening_s = Money(opening).as_str()

        if fmt == "csv":
            body = build_statement_csv(presented)
            logger.info(
                "bank.statement.exported",
                outcome="ok",
                format="csv",
                account_id=account.id,
                subject=subject,
                rows=len(presented),
            )
            return body, "text/csv; charset=utf-8", "statement.csv"

        # Statement PDFs are filter-dependent and mutate as the ledger grows —
        # do not S3-cache them (receipts are immutable per tx).
        pdf = build_statement_pdf(
            holder_name=holder_name,
            account_display=display,
            currency=account.currency,
            period_label=period,
            opening_balance=opening_s,
            closing_balance=closing,
            rows=presented,
        )
        logger.info(
            "bank.statement.exported",
            outcome="ok",
            format="pdf",
            account_id=account.id,
            subject=subject,
            rows=len(presented),
        )
        return pdf, "application/pdf", "statement.pdf"

    async def transfer(
        self,
        subject: str,
        *,
        destination_account_id: str | None = None,
        destination_account: str | None = None,
        destination_document: str | None = None,
        amount: str,
        memo: str | None = None,
        source_account_id: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        return await self._transfers.transfer(
            subject,
            amount=amount,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            destination_account=destination_account,
            destination_document=destination_document,
            memo=memo,
            request_id=request_id,
            idempotency_key=idempotency_key,
            source_ip=source_ip,
            user_agent=user_agent,
        )

    async def withdraw(
        self,
        subject: str,
        *,
        amount: str,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        money = parse_positive_money(amount)
        max_withdraw = Money(self._settings.max_withdraw_amount)
        if money.amount > max_withdraw.amount:
            raise TransferLimitExceeded(money.as_str(), max_withdraw.as_str())

        origin = await self._transfers.require_onboarded_account(subject)
        row = await self._session.get(Account, origin.id)
        assert row is not None
        await self._ledger.withdraw(
            row,
            money.amount,
            actor_subject=subject,
            request_id=request_id,
            idempotency_key=idempotency_key or f"withdraw:{subject}:{request_id}",
            source_ip=source_ip,
            user_agent=user_agent,
        )
        await self._session.refresh(row)
        return {
            "id": row.id,
            "display_number": row.display_number,
            "balance": Money(row.balance_cached).as_str(),
            "currency": row.currency,
        }

    async def _resolve_owned_checking(
        self,
        subject: str,
        account_id: str | None,
    ) -> AccountRecord:
        if account_id:
            return await self._require_owned_account(subject, account_id)
        return await self._require_owned_checking(subject)

    async def _require_owned_account(
        self,
        subject: str,
        account_id: str,
    ) -> AccountRecord:
        user = await self._users.get(subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        account = await self._accounts.get(account_id)
        if account is None or account.kind != "checking":
            raise AccountNotFound(account_id)
        if account.owner_subject != subject:
            raise ForbiddenAccountAccess(account_id)
        return account

    async def _require_owned_checking(self, subject: str) -> AccountRecord:
        user = await self._users.get(subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if account is None:
            raise AccountNotFound("checking")
        if account.owner_subject != subject:
            raise ForbiddenAccountAccess(account.id)
        return account

    async def _present_rows(self, rows, *, currency: str) -> list[dict]:
        cp_map = await self._counterparty_map(rows)
        return [
            present_transaction(
                tx_id=row.id,
                account_id=row.account_id,
                amount=row.amount,
                tx_type=row.type,
                counterparty_account_id=row.counterparty_account_id,
                memo=row.memo,
                created_at=row.created_at,
                currency=currency,
                counterparty=cp_map.get(row.counterparty_account_id or ""),
            )
            for row in rows
        ]

    async def _counterparty_map(self, rows) -> dict[str, CounterpartyContext]:
        ids = sorted(
            {r.counterparty_account_id for r in rows if r.counterparty_account_id}
        )
        accounts = await self._accounts.get_many(ids)
        owner_ids = {a.owner_subject for a in accounts.values() if a.owner_subject}
        holders: dict[str, Holder] = {}
        for oid in owner_ids:
            holder = await self._session.get(Holder, oid)
            if holder is not None:
                holders[oid] = holder
        out: dict[str, CounterpartyContext] = {}
        for aid, acc in accounts.items():
            holder = holders.get(acc.owner_subject or "")
            display = acc.display_number
            if (
                display is None
                and acc.account_number is not None
                and acc.digit is not None
            ):
                display = format_account_display(acc.account_number, acc.digit)
            out[aid] = CounterpartyContext(
                account_id=aid,
                display_number=display,
                holder_name=holder.full_name if holder else None,
                document_number=holder.document_number if holder else None,
            )
        return out

    async def _parties_for(self, row, account: AccountRecord) -> dict:
        cp_map = await self._counterparty_map([row])
        own_holder = await self._session.get(Holder, account.owner_subject or "")
        own = {
            "account_id": account.id,
            "display_number": account.display_number,
            "holder_name": title_case_name(
                own_holder.full_name if own_holder else None
            ),
            "document_masked": mask_document(
                own_holder.document_number if own_holder else None
            ),
        }
        cp = cp_map.get(row.counterparty_account_id or "")
        other = {
            "account_id": row.counterparty_account_id,
            "display_number": cp.display_number if cp else None,
            "holder_name": title_case_name(cp.holder_name if cp else None),
            "document_masked": mask_document(cp.document_number if cp else None)
            if cp
            else None,
        }
        amount = Decimal(str(row.amount))
        if amount >= 0:
            return {"origin": other, "destination": own}
        return {"origin": own, "destination": other}

    @staticmethod
    def _optional_decimal(raw: str | None) -> Decimal | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _types_for_filter(tx_type: str | None) -> list[str] | None:
        if not tx_type or tx_type in {"all", ""}:
            return None
        key = tx_type.strip().lower()
        aliases = {
            "transfer": ["transfer_in", "transfer_out", "pix_in", "pix_out"],
            "grant": ["demo_grant", "deposit", "interest", "refund"],
            "withdraw": ["withdraw"],
        }
        if key in aliases:
            return aliases[key]
        return [key]

    @staticmethod
    def _parse_day_bounds(
        date_from: str | None,
        date_to: str | None,
    ) -> tuple[datetime | None, datetime | None]:
        start = DemoBankService._parse_utc_day(date_from, end=False)
        end = DemoBankService._parse_utc_day(date_to, end=True)
        return start, end

    @staticmethod
    def _parse_utc_day(raw: str | None, *, end: bool) -> datetime | None:
        if not raw or not str(raw).strip():
            return None
        text = str(raw).strip()[:10]
        try:
            d = date.fromisoformat(text)
        except ValueError:
            return None
        if end:
            next_day = d + timedelta(days=1)
            return datetime.combine(next_day, time.min, tzinfo=UTC)
        return datetime.combine(d, time.min, tzinfo=UTC)

    @staticmethod
    def _period_label(date_from: str | None, date_to: str | None) -> str:
        if date_from and date_to:
            return f"{date_from} — {date_to}"
        if date_from:
            return f"from {date_from}"
        if date_to:
            return f"until {date_to}"
        return "all available"

    @staticmethod
    def _wire_onboarding_status(status: str) -> str:
        """Surface mid-KYC as incomplete so clients can list + deep-link to wizard."""
        if status in {"completed", "skipped"}:
            return status
        return "incomplete"

    @staticmethod
    def _view(
        account: AccountRecord,
        onboarding_status: str,
        *,
        demo_credited: bool,
        holder_name: str | None = None,
    ) -> DemoAccountView:
        return DemoAccountView(
            id=account.id,
            balance=Money(account.balance).as_str(),
            currency=account.currency,
            kind=account.kind,
            status=account.status,
            onboarding_status=DemoBankService._wire_onboarding_status(onboarding_status),
            demo_credited=demo_credited,
            account_number=account.account_number,
            digit=account.digit,
            display_number=account.display_number,
            holder_name=holder_name,
        )
