from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.errors import OnboardingError
from app.models.account import Account
from app.models.holder import Holder
from app.repositories.user_repository import OnboardingRepository, UserRepository
from app.services.onboarding_accounts import resolve_onboarding_account

logger = get_logger(__name__)

TOS_POLICY = "demo-bank-tos-v1"
DD_POLICY = "demo-dd-v1"
DD_SKIP_POLICY = "demo-dd-skip-v1"
ALLOWED_DOC_TYPES = frozenset({"identity_document", "address_proof"})
_TERMINAL_SESSION = frozenset({"skipped", "approved_demo"})


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._onboarding = OnboardingRepository(session)

    async def get_status(
        self,
        subject: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        await self._users.upsert(subject)
        try:
            account = await resolve_onboarding_account(
                self._session,
                subject,
                account_id,
                create_if_missing=False,
                allow_single_ready=True,
            )
        except OnboardingError as exc:
            if str(exc) == "onboarding session not started":
                return await self._empty_status(subject)
            raise
        return await self._status_for(subject, account)

    async def start(
        self,
        subject: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        await self._users.upsert(subject)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id,
            create_if_missing=True,
            allow_single_ready=False,
        )
        session = await self._onboarding.latest_session(subject, account.id)
        if session is None or session.status in _TERMINAL_SESSION:
            session = await self._onboarding.create_session(subject, account.id)
        account.onboarding_status = "in_progress"
        await self._session.flush()
        logger.info(
            "onboarding_started",
            subject=subject,
            account_id=account.id,
            session_id=session.id,
        )
        return await self._status_for(subject, account)

    async def consent(self, subject: str, policy_version: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        if policy_version not in {TOS_POLICY, DD_POLICY, DD_SKIP_POLICY}:
            raise OnboardingError(f"unknown policy_version {policy_version}")
        await self._onboarding.record_consent(subject, policy_version)
        logger.info("consent_recorded", subject=subject, policy=policy_version)
        return {"ok": True, "policy_version": policy_version}

    async def skip(
        self,
        subject: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        await self._users.upsert(subject)
        await self._onboarding.record_consent(subject, DD_SKIP_POLICY)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id,
            create_if_missing=True,
            allow_single_ready=True,
        )
        session = await self._onboarding.latest_session(subject, account.id)
        if session is None:
            session = await self._onboarding.create_session(subject, account.id)
        session.status = "skipped"
        session.skipped_at = datetime.now(UTC)
        account.onboarding_status = "skipped"
        await self._session.flush()
        logger.info(
            "onboarding_skipped",
            subject=subject,
            account_id=account.id,
            session_id=session.id,
        )
        return await self._status_for(subject, account)

    async def attach_document(
        self,
        subject: str,
        *,
        doc_type: str,
        pde_extraction_id: str | None = None,
        summary: dict[str, Any] | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        if doc_type not in ALLOWED_DOC_TYPES:
            raise OnboardingError(f"unsupported doc_type {doc_type}")
        await self._users.upsert(subject)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id,
            create_if_missing=True,
            allow_single_ready=False,
        )
        session = await self._onboarding.latest_session(subject, account.id)
        if session is None or session.status in _TERMINAL_SESSION:
            session = await self._onboarding.create_session(subject, account.id)
            account.onboarding_status = "in_progress"
            await self._session.flush()

        safe_summary = _redact_summary(summary) if summary else None
        await self._onboarding.add_document(
            session.id,
            doc_type,
            pde_extraction_id=pde_extraction_id,
            status="extracted" if pde_extraction_id else "pending",
            summary_json=safe_summary,
        )
        logger.info(
            "onboarding_document_attached",
            subject=subject,
            account_id=account.id,
            doc_type=doc_type,
            has_pde_id=bool(pde_extraction_id),
        )
        return await self._status_for(subject, account)

    async def complete(
        self,
        subject: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        await self._users.upsert(subject)
        account = await resolve_onboarding_account(
            self._session,
            subject,
            account_id,
            create_if_missing=False,
            allow_single_ready=True,
        )
        session = await self._onboarding.latest_session(subject, account.id)
        if session is None:
            raise OnboardingError("onboarding session not started")
        if session.status == "skipped":
            return await self._status_for(subject, account)
        session.status = "approved_demo"
        session.completed_at = datetime.now(UTC)
        account.onboarding_status = "completed"
        await self._session.flush()
        logger.info(
            "onboarding_completed",
            subject=subject,
            account_id=account.id,
            session_id=session.id,
        )
        return await self._status_for(subject, account)

    async def _empty_status(self, subject: str) -> dict[str, Any]:
        return {
            "onboarding_status": "not_started",
            "account_id": None,
            "session_id": None,
            "session_status": None,
            "documents": [],
            "skippable": True,
            "demo": True,
            "holder": await self._holder_public(subject),
        }

    async def _status_for(self, subject: str, account: Account) -> dict[str, Any]:
        session = await self._onboarding.latest_session(subject, account.id)
        docs = []
        if session is not None:
            docs = [
                {
                    "id": d.id,
                    "doc_type": d.doc_type,
                    "status": d.status,
                    "pde_extraction_id": d.pde_extraction_id,
                }
                for d in await self._onboarding.list_documents(session.id)
            ]
        return {
            "onboarding_status": account.onboarding_status,
            "account_id": account.id,
            "session_id": session.id if session else None,
            "session_status": session.status if session else None,
            "documents": docs,
            "skippable": True,
            "demo": True,
            "holder": await self._holder_public(subject),
        }

    async def _holder_public(self, subject: str) -> dict[str, Any] | None:
        holder = await self._session.get(Holder, subject)
        if holder is None:
            return None
        birth = holder.birth_date.isoformat() if holder.birth_date else None
        return {
            "full_name": holder.full_name,
            "birth_date": birth,
            "document_type": holder.document_type,
            "document_number": holder.document_number,
            "cep": holder.cep,
            "street": holder.street,
            "number": holder.number,
            "complement": holder.complement,
            "neighborhood": holder.neighborhood,
            "city": holder.city,
            "state": holder.state,
            "email": holder.email,
            "phone": holder.phone,
        }


def _redact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    sensitive = {
        "cpf",
        "cnpj",
        "rg",
        "document_number",
        "numero_documento",
        "card_number",
    }
    out: dict[str, Any] = {}
    for key, value in summary.items():
        if key.lower() in sensitive:
            out[key] = "***REDACTED***"
        elif isinstance(value, dict):
            out[key] = _redact_summary(value)
        else:
            out[key] = value
    return out
