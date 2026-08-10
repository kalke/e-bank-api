from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.money import Money, parse_positive_money
from app.errors import (
    AccountNotFound,
    ForbiddenAccountAccess,
    InsufficientFunds,
    TransferLimitExceeded,
)
from app.repositories.account_repository import AccountRecord, AccountRepository
from app.repositories.user_repository import (
    DemoGrantRepository,
    OnboardingRepository,
    UserRepository,
)

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


class DemoBankService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AccountRepository(session)
        self._users = UserRepository(session)
        self._grants = DemoGrantRepository(session)
        self._onboarding = OnboardingRepository(session)
        self._settings = get_settings()

    async def bootstrap(
        self,
        subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> DemoAccountView:
        user = await self._users.upsert(
            subject,
            email=email,
            display_name=display_name,
        )
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if account is None:
            account_id = f"chk_{uuid4().hex[:16]}"
            account = await self._accounts.create(
                account_id,
                Decimal("0"),
                owner_subject=subject,
                kind="checking",
                currency=self._settings.welcome_currency,
                overdraft_limit=Decimal("0"),
            )

        grant = await self._grants.get(subject)
        if grant is None:
            welcome = Money(self._settings.welcome_amount)
            updated = await self._accounts.record_transaction(
                account.id,
                welcome.amount,
                "demo_grant",
                actor_subject=subject,
                request_id=request_id,
                memo="Welcome demo funds",
            )
            await self._grants.create(
                subject,
                welcome.amount,
                self._settings.welcome_currency,
            )
            await self._users.mark_demo_credited(subject)
            account = updated
            logger.info(
                "demo_grant_credited",
                subject=subject,
                amount=welcome.as_str(),
                account_id=account.id,
            )
        else:
            # refresh balance
            refreshed = await self._accounts.get(account.id)
            if refreshed is not None:
                account = refreshed

        return self._view(account, user.onboarding_status, demo_credited=True)

    async def get_my_account(self, subject: str) -> DemoAccountView:
        user = await self._users.get(subject)
        account = await self._accounts.get_by_owner_kind(subject, "checking")
        if account is None:
            raise AccountNotFound("checking")
        status = user.onboarding_status if user else "not_started"
        credited = user.demo_credited_at is not None if user else False
        return self._view(account, status, demo_credited=credited)

    async def list_transactions(
        self,
        subject: str,
        *,
        limit: int = 20,
        cursor: int | None = None,
    ) -> list[dict]:
        account = await self._require_owned_checking(subject)
        rows = await self._accounts.list_transactions(
            account.id,
            limit=min(limit, 100),
            before_id=cursor,
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
        destination_account_id: str,
        amount: str,
        memo: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        money = parse_positive_money(amount)
        max_transfer = Money(self._settings.max_transfer_amount)
        if money.amount > max_transfer.amount:
            raise TransferLimitExceeded(money.as_str(), max_transfer.as_str())

        origin = await self._require_owned_checking(subject)
        if destination_account_id == origin.id:
            raise TransferLimitExceeded(money.as_str(), "0.00")

        await self._accounts.lock_accounts_for_update(origin.id, destination_account_id)
        origin = await self._accounts.get(origin.id)
        if origin is None or origin.owner_subject != subject:
            raise ForbiddenAccountAccess()

        destination = await self._accounts.get(destination_account_id)
        if destination is None:
            raise AccountNotFound(destination_account_id)

        if origin.balance - money.amount < origin.overdraft_limit:
            raise InsufficientFunds(origin.id)

        updated_origin = await self._accounts.record_transaction(
            origin.id,
            -money.amount,
            "transfer_out",
            destination_account_id,
            actor_subject=subject,
            request_id=request_id,
            memo=memo,
        )
        updated_dest = await self._accounts.record_transaction(
            destination_account_id,
            money.amount,
            "transfer_in",
            origin.id,
            actor_subject=subject,
            request_id=request_id,
            memo=memo,
        )
        logger.info(
            "demo_transfer_completed",
            subject=subject,
            origin=origin.id,
            destination=destination_account_id,
            amount=money.as_str(),
        )
        return {
            "origin": {
                "id": updated_origin.id,
                "balance": Money(updated_origin.balance).as_str(),
            },
            "destination": {
                "id": updated_dest.id,
                "balance": Money(updated_dest.balance).as_str(),
            },
        }

    async def withdraw(
        self,
        subject: str,
        *,
        amount: str,
        request_id: str | None = None,
    ) -> dict:
        money = parse_positive_money(amount)
        max_withdraw = Money(self._settings.max_withdraw_amount)
        if money.amount > max_withdraw.amount:
            raise TransferLimitExceeded(money.as_str(), max_withdraw.as_str())

        account = await self._require_owned_checking(subject)
        locked = await self._accounts.get_for_update(account.id)
        if locked is None or locked.owner_subject != subject:
            raise ForbiddenAccountAccess(account.id)

        if locked.balance - money.amount < locked.overdraft_limit:
            raise InsufficientFunds(locked.id)

        updated = await self._accounts.record_transaction(
            locked.id,
            -money.amount,
            "withdraw",
            actor_subject=subject,
            request_id=request_id,
            memo="Demo ATM withdraw",
        )
        return {
            "id": updated.id,
            "balance": Money(updated.balance).as_str(),
            "currency": updated.currency,
        }

    async def _require_owned_checking(self, subject: str) -> AccountRecord:
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
    ) -> DemoAccountView:
        return DemoAccountView(
            id=account.id,
            balance=Money(account.balance).as_str(),
            currency=account.currency,
            kind=account.kind,
            status=account.status,
            onboarding_status=onboarding_status,
            demo_credited=demo_credited,
        )
