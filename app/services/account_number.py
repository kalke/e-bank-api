"""Sequential account number + random digit generator."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.account import Account

ACCOUNT_NUMBER_START = 1


@dataclass(frozen=True)
class AccountIdentity:
    account_number: int
    digit: int

    @property
    def display(self) -> str:
        return f"{self.account_number:06d}-{self.digit}"


class AccountNumberGenerator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()

    async def next_identity(self) -> AccountIdentity:
        number = await self._next_number()
        digit = secrets.randbelow(10)
        return AccountIdentity(account_number=number, digit=digit)

    async def _next_number(self) -> int:
        start = int(
            getattr(self._settings, "account_number_start", ACCOUNT_NUMBER_START)
        )
        bind = self._session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            result = await self._session.execute(
                text("SELECT nextval('account_number_seq')")
            )
            return int(result.scalar_one())

        result = await self._session.execute(
            select(func.coalesce(func.max(Account.account_number), start - 1))
        )
        current = int(result.scalar_one())
        pending = int(self._session.info.get("account_number_pending", start - 1))
        number = max(current, pending) + 1
        if number < start:
            number = start
        self._session.info["account_number_pending"] = number
        return number
