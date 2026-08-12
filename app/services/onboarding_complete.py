"""Complete onboarding: holder + account + welcome grant in one transaction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.money import Money
from app.domain.validation import (
    require_adult,
    validate_cep,
    validate_document,
    validate_email,
    validate_phone,
)
from app.errors import OnboardingError
from app.models.account import Account
from app.models.holder import Holder
from app.models.transaction import Transaction
from app.repositories.user_repository import OnboardingRepository, UserRepository
from app.services.demo_service import DemoAccountView
from app.services.ledger import IdempotentReplay, LedgerService
from app.services.onboarding_accounts import (
    create_draft_checking,
    resolve_onboarding_account,
)
from app.services.onboarding_service import DD_SKIP_POLICY, TOS_POLICY

logger = get_logger(__name__)


class OnboardingCompletionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._onboarding = OnboardingRepository(session)
        self._ledger = LedgerService(session)
        self._settings = get_settings()

    async def complete(
        self,
        subject: str,
        payload: dict[str, Any],
        *,
        email: str | None = None,
        request_id: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        idempotency_key: str | None = None,
        account_id: str | None = None,
    ) -> DemoAccountView:
        await self._users.upsert(subject, email=email)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id or payload.get("account_id"),
            create_if_missing=True,
        )
        await self._onboarding.ensure_session(subject, account.id)

        holder_data = self._validate_full(payload)
        await self._onboarding.record_consent(subject, TOS_POLICY)
        logger.info("tos_accepted", subject=subject)

        return await self._finish_account(
            subject,
            account,
            holder_data,
            onboarding_status="completed",
            session_status="approved_demo",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            idempotency_key=idempotency_key,
        )

    async def skip_and_open(
        self,
        subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        request_id: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        idempotency_key: str | None = None,
        account_id: str | None = None,
    ) -> DemoAccountView:
        await self._users.upsert(subject, email=email, display_name=display_name)
        await self._onboarding.record_consent(subject, DD_SKIP_POLICY)
        await self._onboarding.record_consent(subject, TOS_POLICY)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id,
            create_if_missing=True,
        )
        await self._onboarding.ensure_session(subject, account.id)

        holder = await self._session.get(Holder, subject)
        if holder is None:
            name = display_name or (email.split("@")[0] if email else "Demo User")
            holder_data = {
                "full_name": name,
                "birth_date": None,
                "document_type": None,
                "document_number": None,
                "cep": None,
                "street": None,
                "number": None,
                "complement": None,
                "neighborhood": None,
                "city": None,
                "state": None,
                "email": email,
                "phone": None,
            }
        else:
            holder_data = None

        return await self._finish_account(
            subject,
            account,
            holder_data,
            onboarding_status="skipped",
            session_status="skipped",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            idempotency_key=idempotency_key,
        )

    async def open_extra_draft(
        self,
        subject: str,
        *,
        holder_name: str,
    ) -> DemoAccountView:
        account = await create_draft_checking(self._session, subject)
        await self._onboarding.create_session(subject, account.id)
        await self._session.refresh(account)
        logger.info(
            "extra_account_opened",
            subject=subject,
            account_display=account.display_number,
        )
        return self._view(
            account,
            "in_progress",
            demo_credited=False,
            holder_name=holder_name,
        )

    async def _finish_account(
        self,
        subject: str,
        account: Account,
        holder_data: dict[str, Any] | None,
        *,
        onboarding_status: str,
        session_status: str,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
        idempotency_key: str | None,
    ) -> DemoAccountView:
        _ = idempotency_key
        holder = await self._upsert_holder(subject, holder_data)
        if account.account_number is None or account.digit is None:
            from app.services.account_number import AccountNumberGenerator

            identity = await AccountNumberGenerator(self._session).next_identity()
            account.account_number = identity.account_number
            account.digit = identity.digit
            await self._session.flush()

        demo_credited = await self._ensure_welcome(
            account,
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )

        session = await self._onboarding.latest_session(subject, account.id)
        if session is not None:
            session.status = session_status
            now = datetime.now(UTC)
            if session_status == "skipped":
                session.skipped_at = now
            else:
                session.completed_at = now
        account.onboarding_status = onboarding_status
        await self._session.flush()
        await self._session.refresh(account)

        logger.info(
            "account_opened",
            subject=subject,
            account_id=account.id,
            account_display=account.display_number,
            status=onboarding_status,
        )
        return self._view(
            account,
            onboarding_status,
            demo_credited=demo_credited,
            holder_name=holder.full_name if holder else None,
        )

    async def _upsert_holder(
        self,
        subject: str,
        holder_data: dict[str, Any] | None,
    ) -> Holder | None:
        holder = await self._session.get(Holder, subject)
        if holder_data is None:
            return holder
        if holder is None:
            holder = Holder(subject=subject, full_name=holder_data["full_name"])
            self._session.add(holder)
        for key, value in holder_data.items():
            setattr(holder, key, value)
        await self._session.flush()
        return holder

    async def _ensure_welcome(
        self,
        account: Account,
        *,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> bool:
        locked = await self._session.execute(
            select(Account).where(Account.id == account.id).with_for_update()
        )
        account = locked.scalar_one()
        existing = await self._session.execute(
            select(Transaction.id)
            .where(
                Transaction.account_id == account.id,
                Transaction.type == "demo_grant",
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return True

        welcome = Money(self._settings.welcome_amount)
        try:
            await self._ledger.welcome_grant(
                account,
                welcome.amount,
                actor_subject=account.owner_subject,
                request_id=request_id,
                idempotency_key=f"welcome:{account.id}",
                source_ip=source_ip,
                user_agent=user_agent,
            )
        except IdempotentReplay:
            return True
        return True

    @staticmethod
    def _view(
        account: Account,
        onboarding_status: str,
        *,
        demo_credited: bool,
        holder_name: str | None,
    ) -> DemoAccountView:
        return DemoAccountView(
            id=account.id,
            balance=Money(Decimal(str(account.balance_cached or 0))).as_str(),
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

    def _validate_full(self, payload: dict[str, Any]) -> dict[str, Any]:
        full_name = str(payload.get("full_name") or "").strip()
        if len(full_name) < 2:
            raise OnboardingError("full_name is required")

        birth_raw = payload.get("birth_date")
        if not birth_raw:
            raise OnboardingError("birth_date is required")
        if isinstance(birth_raw, date):
            birth_date = birth_raw
        else:
            birth_date = date.fromisoformat(str(birth_raw))
        require_adult(birth_date)

        doc_raw = str(payload.get("document_number") or "").strip()
        if not doc_raw:
            raise OnboardingError("document_number is required")
        doc_type, document_number = validate_document(doc_raw)

        cep = validate_cep(str(payload.get("cep") or ""))
        street = str(payload.get("street") or "").strip()
        number = str(payload.get("number") or "").strip()
        if not street or not number:
            raise OnboardingError("street and number are required")

        email = validate_email(str(payload.get("email") or ""))
        phone = validate_phone(str(payload.get("phone") or ""))

        if not payload.get("terms_accepted"):
            raise OnboardingError("terms must be accepted")

        return {
            "full_name": full_name,
            "birth_date": birth_date,
            "document_type": doc_type,
            "document_number": document_number,
            "cep": cep,
            "street": street,
            "number": number,
            "complement": str(payload.get("complement") or "").strip() or None,
            "neighborhood": str(payload.get("neighborhood") or "").strip() or None,
            "city": str(payload.get("city") or "").strip() or None,
            "state": str(payload.get("state") or "").strip().upper()[:2] or None,
            "email": email,
            "phone": phone,
        }
