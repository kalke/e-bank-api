"""Resolve transfer recipients by account display or document."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.validation import (
    format_account_display,
    mask_document,
    parse_account_display,
    validate_document,
)
from app.errors import AccountNotFound, OnboardingError
from app.models.account import Account
from app.models.holder import Holder


@dataclass(frozen=True)
class ResolvedRecipient:
    account_id: str
    account_display: str
    holder_name: str
    document_masked: str | None
    owner_subject: str


class RecipientResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        account: str | None = None,
        document: str | None = None,
    ) -> ResolvedRecipient:
        if bool(account) == bool(document):
            raise OnboardingError("provide exactly one of account or document")

        if account:
            number, digit = parse_account_display(account)
            result = await self._session.execute(
                select(Account).where(
                    Account.account_number == number,
                    Account.digit == digit,
                )
            )
            acc = result.scalar_one_or_none()
            if acc is None or acc.status != "active":
                raise AccountNotFound(account)
            holder = await self._holder(acc.owner_subject)
            return ResolvedRecipient(
                account_id=acc.id,
                account_display=format_account_display(number, digit),
                holder_name=holder.full_name if holder else (acc.owner_subject or ""),
                document_masked=mask_document(holder.document_number)
                if holder
                else None,
                owner_subject=acc.owner_subject or "",
            )

        assert document is not None
        _kind, doc = validate_document(document)
        result = await self._session.execute(
            select(Holder).where(Holder.document_number == doc)
        )
        holder = result.scalar_one_or_none()
        if holder is None:
            raise AccountNotFound(doc)
        acc_result = await self._session.execute(
            select(Account).where(
                Account.owner_subject == holder.subject,
                Account.kind == "checking",
                Account.status == "active",
            )
        )
        acc = acc_result.scalar_one_or_none()
        if acc is None or acc.account_number is None or acc.digit is None:
            raise AccountNotFound(doc)
        return ResolvedRecipient(
            account_id=acc.id,
            account_display=format_account_display(acc.account_number, acc.digit),
            holder_name=holder.full_name,
            document_masked=mask_document(holder.document_number),
            owner_subject=holder.subject,
        )

    async def _holder(self, subject: str | None) -> Holder | None:
        if not subject:
            return None
        return await self._session.get(Holder, subject)
