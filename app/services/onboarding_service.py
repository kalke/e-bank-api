from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.errors import OnboardingError
from app.repositories.user_repository import OnboardingRepository, UserRepository

logger = get_logger(__name__)

TOS_POLICY = "demo-bank-tos-v1"
DD_POLICY = "demo-dd-v1"
DD_SKIP_POLICY = "demo-dd-skip-v1"
ALLOWED_DOC_TYPES = frozenset({"identity_document", "address_proof"})


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._onboarding = OnboardingRepository(session)

    async def get_status(self, subject: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        user = await self._users.get(subject)
        session = await self._onboarding.latest_session(subject)
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
            "onboarding_status": user.onboarding_status if user else "not_started",
            "session_id": session.id if session else None,
            "session_status": session.status if session else None,
            "documents": docs,
            "skippable": True,
            "demo": True,
        }

    async def start(self, subject: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        session = await self._onboarding.latest_session(subject)
        if session is None or session.status in {"skipped", "approved_demo"}:
            session = await self._onboarding.create_session(subject)
        await self._users.set_onboarding_status(subject, "in_progress")
        logger.info("onboarding_started", subject=subject, session_id=session.id)
        return await self.get_status(subject)

    async def consent(self, subject: str, policy_version: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        if policy_version not in {TOS_POLICY, DD_POLICY, DD_SKIP_POLICY}:
            raise OnboardingError(f"unknown policy_version {policy_version}")
        await self._onboarding.record_consent(subject, policy_version)
        logger.info("consent_recorded", subject=subject, policy=policy_version)
        return {"ok": True, "policy_version": policy_version}

    async def skip(self, subject: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        await self._onboarding.record_consent(subject, DD_SKIP_POLICY)
        session = await self._onboarding.latest_session(subject)
        if session is None:
            session = await self._onboarding.create_session(subject)
        session.status = "skipped"
        session.skipped_at = datetime.now(UTC)
        await self._users.set_onboarding_status(subject, "skipped")
        logger.info("onboarding_skipped", subject=subject, session_id=session.id)
        return await self.get_status(subject)

    async def attach_document(
        self,
        subject: str,
        *,
        doc_type: str,
        pde_extraction_id: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if doc_type not in ALLOWED_DOC_TYPES:
            raise OnboardingError(f"unsupported doc_type {doc_type}")
        await self._users.upsert(subject)
        session = await self._onboarding.latest_session(subject)
        if session is None or session.status in {"skipped", "approved_demo"}:
            session = await self._onboarding.create_session(subject)
            await self._users.set_onboarding_status(subject, "in_progress")

        # Store redacted/metadata only — never raw document bytes
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
            doc_type=doc_type,
            has_pde_id=bool(pde_extraction_id),
        )
        return await self.get_status(subject)

    async def complete(self, subject: str) -> dict[str, Any]:
        await self._users.upsert(subject)
        session = await self._onboarding.latest_session(subject)
        if session is None:
            raise OnboardingError("onboarding session not started")
        if session.status == "skipped":
            return await self.get_status(subject)
        session.status = "approved_demo"
        session.completed_at = datetime.now(UTC)
        await self._users.set_onboarding_status(subject, "completed")
        logger.info("onboarding_completed", subject=subject, session_id=session.id)
        return await self.get_status(subject)


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
