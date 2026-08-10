from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_bank_write
from app.auth.oidc import Principal
from app.core.config import get_settings
from app.core.database import get_db
from app.repositories.account_repository import AccountRepository
from app.schemas import EventIn
from app.services import Account, AccountService

router = APIRouter(tags=["legacy"])


def _account_out(account: Account) -> dict[str, str | int]:
    return {"id": account.id, "balance": account.balance}


def _service(db: AsyncSession) -> AccountService:
    return AccountService(AccountRepository(db))


@router.post("/reset")
async def reset(
    db: AsyncSession = Depends(get_db),
    _auth: Principal | None = Depends(require_bank_write),
) -> PlainTextResponse:
    if not get_settings().reset_allowed:
        raise HTTPException(status_code=404, detail={"message": "not found"})
    await _service(db).reset()
    return PlainTextResponse(content="OK", status_code=200)


@router.get("/balance")
async def balance(
    account_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _auth: Principal | None = Depends(require_bank_write),
) -> PlainTextResponse:
    value = await _service(db).get_balance(account_id)
    return PlainTextResponse(content=str(value), status_code=200)


@router.post("/event")
async def event(
    body: EventIn,
    db: AsyncSession = Depends(get_db),
    _auth: Principal | None = Depends(require_bank_write),
) -> Response:
    service = _service(db)
    if body.type == "deposit":
        account = await service.deposit(body.destination, body.amount)
        return JSONResponse(
            status_code=201,
            content={"destination": _account_out(account)},
        )
    if body.type == "withdraw":
        account = await service.withdraw(body.origin, body.amount)
        return JSONResponse(
            status_code=201,
            content={"origin": _account_out(account)},
        )
    origin, destination = await service.transfer(
        body.origin,
        body.destination,
        body.amount,
    )
    return JSONResponse(
        status_code=201,
        content={
            "origin": _account_out(origin),
            "destination": _account_out(destination),
        },
    )
