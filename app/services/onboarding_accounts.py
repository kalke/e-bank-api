"""Resolve the checking account that an onboarding call targets."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.ids import new_uuid
from app.errors import AccountNotFound, ForbiddenAccountAccess, OnboardingError
from app.models.account import Account
from app.services.account_number import AccountNumberGenerator

READY_STATUSES = frozenset({"completed", "skipped"})
INCOMPLETE_STATUSES = frozenset({"not_started", "in_progress"})
ACCOUNT_ID_REQUIRED = "account_id is required"


async def list_owned_checking(session: AsyncSession, subject: str) -> list[Account]:
    result = await session.execute(
        select(Account)
        .where(
            Account.owner_subject == subject,
            Account.kind == "checking",
        )
        .order_by(Account.created_at.asc(), Account.id.asc())
    )
    return list(result.scalars().all())


async def get_owned_checking(
    session: AsyncSession,
    subject: str,
    account_id: str,
) -> Account:
    account = await session.get(Account, account_id)
    if account is None or account.kind != "checking":
        raise AccountNotFound(account_id)
    if account.owner_subject != subject:
        raise ForbiddenAccountAccess(account_id)
    return account


async def create_draft_checking(session: AsyncSession, subject: str) -> Account:
    identity = await AccountNumberGenerator(session).next_identity()
    settings = get_settings()
    account = Account(
        id=new_uuid(),
        owner_subject=subject,
        kind="checking",
        currency=settings.welcome_currency,
        status="active",
        account_number=identity.account_number,
        digit=identity.digit,
        balance_cached=Decimal("0"),
        overdraft_limit=Decimal("0"),
        onboarding_status="in_progress",
    )
    session.add(account)
    await session.flush()
    return account


async def resolve_onboarding_account(
    session: AsyncSession,
    subject: str,
    account_id: str | None,
    *,
    create_if_missing: bool,
    allow_single_ready: bool = False,
) -> Account:
    if account_id:
        return await get_owned_checking(session, subject, account_id)

    rows = await list_owned_checking(session, subject)
    incomplete = [row for row in rows if row.onboarding_status in INCOMPLETE_STATUSES]
    if len(incomplete) == 1:
        return incomplete[0]
    if not rows:
        if create_if_missing:
            return await create_draft_checking(session, subject)
        raise OnboardingError("onboarding session not started")
    if allow_single_ready and len(rows) == 1 and not incomplete:
        return rows[0]
    raise OnboardingError(ACCOUNT_ID_REQUIRED)


def require_ready(account: Account) -> None:
    if account.onboarding_status not in READY_STATUSES:
        raise OnboardingError("complete onboarding before using the bank")
