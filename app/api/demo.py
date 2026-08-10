from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_authenticated_bank_write
from app.auth.oidc import Principal
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import RateLimiter, RateLimitExceeded
from app.schemas import (
    ConsentIn,
    DemoAccountOut,
    DemoMetaOut,
    OnboardingDocumentIn,
    TransferIn,
    WithdrawIn,
)
from app.services.demo_service import DemoAccountView, DemoBankService
from app.services.onboarding_service import OnboardingService

router = APIRouter(prefix="/v1", tags=["demo"])


def _demo_account_out(view: DemoAccountView) -> DemoAccountOut:
    return DemoAccountOut(
        id=view.id,
        balance=view.balance,
        currency=view.currency,
        kind=view.kind,
        status=view.status,
        onboarding_status=view.onboarding_status,
        demo_credited=view.demo_credited,
        demo=True,
    )


async def _enforce_rate_limit(request: Request, principal: Principal) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise RateLimitExceeded(settings.rate_limit_window_seconds)
    allowed, remaining, retry_after = await limiter.allow(principal.subject)
    request.state.rate_limit_remaining = remaining
    if not allowed:
        raise RateLimitExceeded(retry_after)


@router.get("/demo/meta", response_model=DemoMetaOut)
async def demo_meta() -> DemoMetaOut:
    settings = get_settings()
    return DemoMetaOut(
        demo=True,
        welcome_amount=settings.welcome_amount,
        currency=settings.welcome_currency,
        disclaimer=settings.demo_disclaimer,
        features=[
            "welcome_grant",
            "skippable_due_diligence",
            "transfer",
            "withdraw",
            "transaction_history",
        ],
    )


@router.post("/demo/bootstrap", response_model=DemoAccountOut)
async def bootstrap(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> DemoAccountOut:
    await _enforce_rate_limit(request, principal)
    view = await DemoBankService(db).bootstrap(
        principal.subject,
        email=principal.email or None,
        request_id=getattr(request.state, "request_id", None),
    )
    return _demo_account_out(view)


@router.get("/me/account", response_model=DemoAccountOut)
async def my_account(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> DemoAccountOut:
    view = await DemoBankService(db).get_my_account(principal.subject)
    return _demo_account_out(view)


@router.get("/me/transactions")
async def my_transactions(
    limit: int = 20,
    cursor: int | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    items = await DemoBankService(db).list_transactions(
        principal.subject,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = items[-1]["id"] if items else None
    return {"transactions": items, "next_cursor": next_cursor, "demo": True}


@router.post("/me/transfer")
async def transfer(
    body: TransferIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    await _enforce_rate_limit(request, principal)
    result = await DemoBankService(db).transfer(
        principal.subject,
        destination_account_id=body.destination_account_id,
        amount=body.amount,
        memo=body.memo,
        request_id=getattr(request.state, "request_id", None),
    )
    result["demo"] = True
    return result


@router.post("/me/withdraw")
async def withdraw(
    body: WithdrawIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    await _enforce_rate_limit(request, principal)
    result = await DemoBankService(db).withdraw(
        principal.subject,
        amount=body.amount,
        request_id=getattr(request.state, "request_id", None),
    )
    result["demo"] = True
    return result


@router.get("/onboarding")
async def onboarding_status(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).get_status(principal.subject)


@router.post("/onboarding/start")
async def onboarding_start(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).start(principal.subject)


@router.post("/onboarding/consent")
async def onboarding_consent(
    body: ConsentIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).consent(principal.subject, body.policy_version)


@router.post("/onboarding/skip")
async def onboarding_skip(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).skip(principal.subject)


@router.post("/onboarding/documents")
async def onboarding_documents(
    body: OnboardingDocumentIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).attach_document(
        principal.subject,
        doc_type=body.doc_type,
        pde_extraction_id=body.pde_extraction_id,
        summary=body.summary,
    )


@router.post("/onboarding/complete")
async def onboarding_complete(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    return await OnboardingService(db).complete(principal.subject)
