from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import configure_logging, get_logger
from app.core.middleware import RequestLoggingMiddleware
from app.errors import DomainError
from app.schemas import EventIn
from app.services import Account, AccountService
from app.store import InMemoryStore

configure_logging()
logger = get_logger(__name__)

store = InMemoryStore()
service = AccountService(store)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info("application_startup", status="ready")
    try:
        yield
    finally:
        logger.info("application_shutdown", status="stopped")


app = FastAPI(title="EBANX Bank API", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)


def _account_out(account: Account) -> dict[str, str | int]:
    return {"id": account.id, "balance": account.balance}


@app.exception_handler(DomainError)
def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    log = get_logger("app.errors")
    payload = {
        "status_code": exc.status_code,
        "message": str(exc),
        "path": request.url.path,
        "method": request.method,
        "request_id": request_id,
    }

    if exc.status_code >= 500:
        log.error("domain_error", **payload)
    else:
        log.warning("domain_error", **payload)

    return JSONResponse(
        status_code=exc.status_code,
        content={"message": str(exc)},
    )


@app.exception_handler(Exception)
def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, (RequestValidationError, StarletteHTTPException)):
        raise exc

    request_id = getattr(request.state, "request_id", None)
    get_logger("app.errors").error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        request_id=request_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
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
    origin, destination = service.transfer(body.origin, body.destination, body.amount)
    return JSONResponse(
        status_code=201,
        content={
            "origin": _account_out(origin),
            "destination": _account_out(destination),
        },
    )
