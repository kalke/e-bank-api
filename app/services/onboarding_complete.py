"""Complete onboarding: holder + account + welcome grant in one transaction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logger import get_logger
from app.domain.ids import new_uuid
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
from app.repositories.user_repository import (
    DemoGrantRepository,
    OnboardingRepository,
    UserRepository,
)
from app.services.account_number import AccountNumberGenerator
from app.services.demo_service import DemoAccountView
from app.services.ledger import LedgerService
from app.services.onboarding_service import DD_SKIP_POLICY, TOS_POLICY

logger = get_logger(__name__)


class OnboardingCompletionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._onboarding = OnboardingRepository(session)
        self._grants = DemoGrantRepository(session)
        self._numbers = AccountNumberGenerator(session)
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
    ) -> DemoAccountView:
        await self._users.upsert(subject, email=email)
        session = await self._onboarding.latest_session(subject)
        if session is None:
            await self._onboarding.create_session(subject)

        holder_data = self._validate_full(payload)
        await self._onboarding.record_consent(subject, TOS_POLICY)
        logger.info("tos_accepted", subject=subject)

        return await self._create_holder_and_account(
            subject,
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
    ) -> DemoAccountView:
        await self._users.upsert(subject, email=email, display_name=display_name)
        await self._onboarding.record_consent(subject, DD_SKIP_POLICY)
        await self._onboarding.record_consent(subject, TOS_POLICY)
        session = await self._onboarding.latest_session(subject)
        if session is None:
            await self._onboarding.create_session(subject)

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
        return await self._create_holder_and_account(
            subject,
            holder_data,
            onboarding_status="skipped",
            session_status="skipped",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            idempotency_key=idempotency_key,
        )

    async def _create_holder_and_account(
        self,
        subject: str,
        holder_data: dict[str, Any],
        *,
        onboarding_status: str,
        session_status: str,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
        idempotency_key: str | None,
    ) -> DemoAccountView:
        existing = await self._session.execute(
            select(Account).where(
                Account.owner_subject == subject,
                Account.kind == "checking",
            )
        )
        account = existing.scalar_one_or_none()
        if account is not None:
            user = await self._users.get(subject)
            return self._view(
                account,
                user.onboarding_status if user else onboarding_status,
                demo_credited=user.demo_credited_at is not None if user else False,
                holder_name=holder_data.get("full_name"),
            )

        holder = await self._session.get(Holder, subject)
        if holder is None:
            holder = Holder(subject=subject, full_name=holder_data["full_name"])
            self._session.add(holder)
        for key, value in holder_data.items():
            setattr(holder, key, value)
        await self._session.flush()

        identity = await self._numbers.next_identity()
        account = Account(
            id=new_uuid(),
            owner_subject=subject,
            kind="checking",
            currency=self._settings.welcome_currency,
            status="active",
            account_number=identity.account_number,
            digit=identity.digit,
            balance_cached=Decimal("0"),
            overdraft_limit=Decimal("0"),
        )
        self._session.add(account)
        await self._session.flush()

        welcome = Money(self._settings.welcome_amount)
        grant = await self._grants.get(subject)
        if grant is None:
            await self._ledger.welcome_grant(
                account,
                welcome.amount,
                actor_subject=subject,
                request_id=request_id,
                idempotency_key=idempotency_key or f"welcome:{subject}",
                source_ip=source_ip,
                user_agent=user_agent,
            )
            await self._grants.create(
                subject,
                welcome.amount,
                self._settings.welcome_currency,
            )
            await self._users.mark_demo_credited(subject)

        session = await self._onboarding.latest_session(subject)
        if session is not None:
            session.status = session_status
            now = datetime.now(UTC)
            if session_status == "skipped":
                session.skipped_at = now
            else:
                session.completed_at = now
        await self._users.set_onboarding_status(subject, onboarding_status)
        await self._session.refresh(account)

        logger.info(
            "account_opened",
            subject=subject,
            account_display=account.display_number,
            status=onboarding_status,
        )
        return self._view(
            account,
            onboarding_status,
            demo_credited=True,
            holder_name=holder.full_name,
        )

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
