from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.money import Money, parse_positive_money
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
        user = await self._users.get(subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if account is None:
            raise AccountNotFound("checking")
        holder = await self._session.get(Holder, subject)
        return self._view(
            account,
            user.onboarding_status,
            demo_credited=user.demo_credited_at is not None,
            holder_name=holder.full_name if holder else None,
        )

    async def list_accounts(self, subject: str) -> list[DemoAccountView]:
        user = await self._users.get(subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            return []
        rows = await self._accounts.list_by_owner_kind(subject, "checking")
        holder = await self._session.get(Holder, subject)
        return [
            self._view(
                row,
                user.onboarding_status,
                demo_credited=user.demo_credited_at is not None,
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
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        rows = await self._accounts.list_by_owner_kind(subject, "checking")
        holder = await self._session.get(Holder, subject)
        for row in rows:
            if row.display_number == display or row.id == display:
                return self._view(
                    row,
                    user.onboarding_status,
                    demo_credited=user.demo_credited_at is not None,
                    holder_name=holder.full_name if holder else None,
                )
        raise ForbiddenAccountAccess(display)

    async def list_transactions(
        self,
        subject: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> list[dict]:
        account = await self._require_owned_checking(subject)
        rows = await self._accounts.list_transactions(
            account.id,
            limit=min(limit, 100),
            before_public_id=cursor,
        )
        return [
            {
                "id": row.id,
                "account_id": row.account_id,
                "amount": Money(row.amount).as_str(),
                "type": row.type,
                "counterparty_account_id": row.counterparty_account_id,
                "memo": row.memo,
                "created_at": row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else str(row.created_at),
            }
            for row in rows
        ]

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
            onboarding_status=onboarding_status,
            demo_credited=demo_credited,
            account_number=account.account_number,
            digit=account.digit,
            display_number=account.display_number,
            holder_name=holder_name,
        )
