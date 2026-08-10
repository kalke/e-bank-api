from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import (
    Consent,
    DemoGrant,
    OnboardingDocument,
    OnboardingSession,
)
from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, subject: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.subject == subject),
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> User:
        user = await self.get(subject)
        if user is None:
            user = User(
                subject=subject,
                email=email or None,
                display_name=display_name or None,
            )
            self._session.add(user)
            await self._session.flush()
            return user
        if email and user.email != email:
            user.email = email
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        await self._session.flush()
        return user

    async def set_onboarding_status(self, subject: str, status: str) -> User:
        user = await self.get(subject)
        if user is None:
            raise ValueError(f"user {subject} not found")
        user.onboarding_status = status
        await self._session.flush()
        return user

    async def mark_demo_credited(self, subject: str) -> None:
        user = await self.get(subject)
        if user is None:
            return
        user.demo_credited_at = datetime.now(UTC)
        await self._session.flush()


class DemoGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, subject: str) -> DemoGrant | None:
        result = await self._session.execute(
            select(DemoGrant).where(DemoGrant.subject == subject),
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        subject: str,
        amount: Decimal,
        currency: str,
        transaction_id: int | None = None,
    ) -> DemoGrant:
        grant = DemoGrant(
            subject=subject,
            amount=amount,
            currency=currency,
            transaction_id=transaction_id,
        )
        self._session.add(grant)
        await self._session.flush()
        return grant


class OnboardingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_session(self, subject: str) -> OnboardingSession | None:
        result = await self._session.execute(
            select(OnboardingSession)
            .where(OnboardingSession.subject == subject)
            .order_by(OnboardingSession.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    async def create_session(self, subject: str) -> OnboardingSession:
        session = OnboardingSession(id=str(uuid4()), subject=subject, status="draft")
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_session(self, session_id: str) -> OnboardingSession | None:
        result = await self._session.execute(
            select(OnboardingSession).where(OnboardingSession.id == session_id),
        )
        return result.scalar_one_or_none()

    async def add_document(
        self,
        session_id: str,
        doc_type: str,
        *,
        pde_extraction_id: str | None = None,
        status: str = "extracted",
        summary_json: dict | None = None,
    ) -> OnboardingDocument:
        doc = OnboardingDocument(
            id=str(uuid4()),
            session_id=session_id,
            doc_type=doc_type,
            pde_extraction_id=pde_extraction_id,
            status=status,
            summary_json=summary_json,
        )
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def list_documents(self, session_id: str) -> list[OnboardingDocument]:
        result = await self._session.execute(
            select(OnboardingDocument).where(
                OnboardingDocument.session_id == session_id,
            ),
        )
        return list(result.scalars().all())

    async def record_consent(self, subject: str, policy_version: str) -> Consent:
        result = await self._session.execute(
            select(Consent).where(
                Consent.subject == subject,
                Consent.policy_version == policy_version,
            ),
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        consent = Consent(subject=subject, policy_version=policy_version)
        self._session.add(consent)
        await self._session.flush()
        return consent
