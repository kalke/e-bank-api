from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Holder(Base):
    __tablename__ = "holders"

    subject: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("users.subject"),
        primary_key=True,
    )
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    street: Mapped[str | None] = mapped_column(String(256), nullable=True)
    number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    complement: Mapped[str | None] = mapped_column(String(128), nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
