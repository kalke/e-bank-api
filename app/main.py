from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.schemas import EventIn
from app.services import Account, AccountService
from app.store import InMemoryStore

store = InMemoryStore()
service = AccountService(store)

app = FastAPI(title="EBANX Bank API")


def _account_out(account: Account) -> dict:
    return {"id": account.id, "balance": account.balance}


def _error_response(status_code: int) -> PlainTextResponse:
    return PlainTextResponse(content="0", status_code=status_code)


@app.post("/reset")
def reset() -> PlainTextResponse:
    service.reset()
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/balance")
def balance(account_id: str = Query(...)) -> PlainTextResponse:
    try:
        value = service.get_balance(account_id)
    except AccountNotFound:
        return _error_response(404)
    return PlainTextResponse(content=str(value), status_code=200)


@app.post("/event")
def event(body: EventIn) -> Response:
    try:
        if body.type == "deposit":
            account = service.deposit(body.destination, body.amount)
            return JSONResponse(
                status_code=201,
                content={"destination": _account_out(account)},
            )
        if body.type == "withdraw":
            account = service.withdraw(body.origin, body.amount)
            return JSONResponse(
                status_code=201,
                content={"origin": _account_out(account)},
            )
        origin, destination = service.transfer(
            body.origin, body.destination, body.amount
        )
        return JSONResponse(
            status_code=201,
            content={
                "origin": _account_out(origin),
                "destination": _account_out(destination),
            },
        )
    except AccountNotFound:
        return _error_response(404)
    except InsufficientFunds as exc:
        return _error_response(400)
    except InvalidAmount:
        return _error_response(400)
