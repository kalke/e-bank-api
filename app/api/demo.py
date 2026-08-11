from fastapi import APIRouter, Depends, Header, Request
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
    OnboardingCompleteIn,
    OnboardingDocumentIn,
    TransferIn,
    TransferResolveIn,
    WithdrawIn,
)
from app.services.cep import CepLookup
from app.services.demo_service import DemoAccountView, DemoBankService
from app.services.onboarding_complete import OnboardingCompletionService
from app.services.onboarding_service import OnboardingService
from app.services.transfer import TransferService

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
        account_number=view.account_number,
        digit=view.digit,
        display_number=view.display_number,
        holder_name=view.holder_name,
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


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.headers.get("x-kalke-client-ip") or (
        request.client.host if request.client else None
    )
    ua = request.headers.get("x-kalke-user-agent") or request.headers.get("user-agent")
    return ip, ua


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
            "onboarding_wizard",
            "skippable_due_diligence",
            "multiple_checking_accounts",
            "transfer",
            "transfer_resolve",
            "withdraw",
            "transaction_history",
            "double_entry_ledger",
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


@router.get("/me/accounts")
async def my_accounts(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    items = await DemoBankService(db).list_accounts(principal.subject)
    return {
        "accounts": [_demo_account_out(v).model_dump() for v in items],
        "demo": True,
    }


@router.post("/me/accounts", response_model=DemoAccountOut)
async def open_additional_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DemoAccountOut:
    await _enforce_rate_limit(request, principal)
    ip, ua = _client_meta(request)
    view = await DemoBankService(db).open_additional_account(
        principal.subject,
        request_id=getattr(request.state, "request_id", None),
        source_ip=ip,
        user_agent=ua,
        idempotency_key=idempotency_key,
    )
    return _demo_account_out(view)


@router.get("/me/accounts/{display}")
async def my_account_detail(
    display: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> DemoAccountOut:
    view = await DemoBankService(db).get_account_by_display(principal.subject, display)
    return _demo_account_out(view)


@router.get("/me/transactions")
async def my_transactions(
    limit: int = 20,
    cursor: str | None = None,
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


@router.post("/me/transfers/resolve")
async def transfer_resolve(
    body: TransferResolveIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    await _enforce_rate_limit(request, principal)
    await TransferService(db).require_onboarded_account(principal.subject)
    result = await TransferService(db).resolve(
        account=body.account,
        document=body.document,
    )
    result["demo"] = True
    return result


@router.post("/me/transfer")
async def transfer(
    body: TransferIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    await _enforce_rate_limit(request, principal)
    ip, ua = _client_meta(request)
    result = await DemoBankService(db).transfer(
        principal.subject,
        source_account_id=body.source_account_id,
        destination_account_id=body.destination_account_id,
        destination_account=body.destination_account,
        destination_document=body.destination_document,
        amount=body.amount,
        memo=body.memo,
        request_id=getattr(request.state, "request_id", None),
        idempotency_key=idempotency_key,
        source_ip=ip,
        user_agent=ua,
    )
    result["demo"] = True
    return result


@router.post("/me/withdraw")
async def withdraw(
    body: WithdrawIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    await _enforce_rate_limit(request, principal)
    ip, ua = _client_meta(request)
    result = await DemoBankService(db).withdraw(
        principal.subject,
        amount=body.amount,
        request_id=getattr(request.state, "request_id", None),
        idempotency_key=idempotency_key,
        source_ip=ip,
        user_agent=ua,
    )
    result["demo"] = True
    return result


@router.get("/cep/{cep}")
async def cep_lookup(
    cep: str,
    request: Request,
    principal: Principal = Depends(require_authenticated_bank_write),
) -> dict:
    await _enforce_rate_limit(request, principal)
    data = await CepLookup().lookup(cep)
    data["demo"] = True
    return data


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


@router.post("/onboarding/skip", response_model=DemoAccountOut)
async def onboarding_skip(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DemoAccountOut:
    await _enforce_rate_limit(request, principal)
    ip, ua = _client_meta(request)
    view = await OnboardingCompletionService(db).skip_and_open(
        principal.subject,
        email=principal.email or None,
        request_id=getattr(request.state, "request_id", None),
        source_ip=ip,
        user_agent=ua,
        idempotency_key=idempotency_key,
    )
    return _demo_account_out(view)


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


@router.post("/onboarding/complete", response_model=DemoAccountOut)
async def onboarding_complete(
    body: OnboardingCompleteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authenticated_bank_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DemoAccountOut:
    await _enforce_rate_limit(request, principal)
    ip, ua = _client_meta(request)
    view = await OnboardingCompletionService(db).complete(
        principal.subject,
        body.model_dump(),
        email=principal.email or None,
        request_id=getattr(request.state, "request_id", None),
        source_ip=ip,
        user_agent=ua,
        idempotency_key=idempotency_key,
    )
    return _demo_account_out(view)
