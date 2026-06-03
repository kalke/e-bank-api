from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.errors import DomainError
from app.schemas import EventIn
from app.services import Account, AccountService
from app.store import InMemoryStore

store = InMemoryStore()
service = AccountService(store)

app = FastAPI(title="EBANX Bank API")


def _account_out(account: Account) -> dict:
    return {"id": account.id, "balance": account.balance}


@app.exception_handler(DomainError)
def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": str(exc)},
    )


@app.post("/reset")
def reset() -> PlainTextResponse:
    service.reset()
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/balance")
def balance(account_id: str = Query(...)) -> PlainTextResponse:
    value = service.get_balance(account_id)
    return PlainTextResponse(content=str(value), status_code=200)


@app.post("/event")
def event(body: EventIn) -> Response:
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
