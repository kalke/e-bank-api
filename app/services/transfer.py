"""Transfer use-case with recipient resolution + ledger postings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.money import Money, parse_positive_money
from app.errors import (
    AccountNotFound,
    ForbiddenAccountAccess,
    OnboardingError,
    SameAccountTransfer,
    TransferLimitExceeded,
)
from app.models.account import Account
from app.models.user import User
from app.services.ledger import IdempotentReplay, LedgerService
from app.services.recipient import RecipientResolver

logger = get_logger(__name__)


class TransferService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ledger = LedgerService(session)
        self._resolver = RecipientResolver(session)
        self._settings = get_settings()

    async def require_onboarded_account(self, subject: str) -> Account:
        user = await self._session.get(User, subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        result = await self._session.execute(
            select(Account)
            .where(
                Account.owner_subject == subject,
                Account.kind == "checking",
            )
            .order_by(Account.created_at.asc(), Account.id.asc())
            .limit(1)
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise AccountNotFound("checking")
        if account.status != "active":
            raise ForbiddenAccountAccess(account.id)
        return account

    async def require_owned_account(
        self,
        subject: str,
        account_id: str,
    ) -> Account:
        user = await self._session.get(User, subject)
        if user is None or user.onboarding_status not in {"completed", "skipped"}:
            raise OnboardingError("complete onboarding before using the bank")
        account = await self._session.get(Account, account_id)
        if account is None or account.owner_subject != subject:
            raise ForbiddenAccountAccess(account_id)
        if account.status != "active":
            raise ForbiddenAccountAccess(account_id)
        return account

    async def resolve(
        self,
        *,
        account: str | None = None,
        document: str | None = None,
    ) -> dict:
        recipient = await self._resolver.resolve(account=account, document=document)
        return {
            "account_id": recipient.account_id,
            "account_display": recipient.account_display,
            "holder_name": recipient.holder_name,
            "document_masked": recipient.document_masked,
        }

    async def transfer(
        self,
        subject: str,
        *,
        amount: str,
        source_account_id: str | None = None,
        destination_account_id: str | None = None,
        destination_account: str | None = None,
        destination_document: str | None = None,
        memo: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        if not idempotency_key:
            raise OnboardingError("Idempotency-Key header is required")

        money = parse_positive_money(amount)
        max_transfer = Money(self._settings.max_transfer_amount)
        if money.amount > max_transfer.amount:
            raise TransferLimitExceeded(money.as_str(), max_transfer.as_str())

        origin = (
            await self.require_owned_account(subject, source_account_id)
            if source_account_id
            else await self.require_onboarded_account(subject)
        )

        if destination_account_id:
            dest = await self._session.get(Account, destination_account_id)
            if dest is None or dest.status != "active":
                raise AccountNotFound(destination_account_id)
        else:
            recipient = await self._resolver.resolve(
                account=destination_account,
                document=destination_document,
            )
            dest = await self._session.get(Account, recipient.account_id)
            if dest is None:
                raise AccountNotFound(recipient.account_id)

        if dest.id == origin.id:
            raise SameAccountTransfer()

        # Lock both rows in stable order
        ids = sorted([origin.id, dest.id])
        for aid in ids:
            await self._session.execute(
                select(Account).where(Account.id == aid).with_for_update()
            )
        origin = await self._session.get(Account, origin.id)
        dest = await self._session.get(Account, dest.id)
        assert origin is not None and dest is not None

        try:
            await self._ledger.transfer(
                origin,
                dest,
                money.amount,
                actor_subject=subject,
                request_id=request_id,
                idempotency_key=idempotency_key,
                source_ip=source_ip,
                user_agent=user_agent,
                reason=memo,
            )
        except IdempotentReplay:
            await self._session.refresh(origin)
            await self._session.refresh(dest)

        await self._session.refresh(origin)
        await self._session.refresh(dest)
        logger.info(
            "transfer_completed",
            subject=subject,
            origin=origin.display_number,
            destination=dest.display_number,
            amount=money.as_str(),
        )
        return {
            "origin": {
                "id": origin.id,
                "display_number": origin.display_number,
                "balance": Money(origin.balance_cached).as_str(),
            },
            "destination": {
                "id": dest.id,
                "display_number": dest.display_number,
                "balance": Money(dest.balance_cached).as_str(),
            },
        }
