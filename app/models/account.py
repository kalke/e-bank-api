from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("owner_subject", "kind", name="uq_accounts_owner_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_subject: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("users.subject"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="checking")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    account_number: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
    )
    digit: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    balance_cached: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    overdraft_limit: Mapped[object] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=0,
        server_default="0",
    )
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

    @property
    def display_number(self) -> str | None:
        if self.account_number is None or self.digit is None:
            return None
        return f"{int(self.account_number):06d}-{int(self.digit)}"
