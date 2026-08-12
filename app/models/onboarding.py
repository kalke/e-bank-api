from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.domain.ids import new_uuid


class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )
    subject: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("users.subject"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("accounts.id"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    skipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    draft_json: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )


class OnboardingDocument(Base):
    __tablename__ = "onboarding_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("onboarding_sessions.id"),
        nullable=False,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pde_extraction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    summary_json: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "policy_version",
            name="uq_consents_subject_policy",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("users.subject"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class DemoGrant(Base):
    __tablename__ = "demo_grants"

    subject: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("users.subject"),
        primary_key=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    transaction_id: Mapped[int | None] = mapped_column(nullable=True)
