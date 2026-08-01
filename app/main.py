import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as redis
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.deps import require_bank_write
from app.auth.oidc import Principal, get_authenticator, oidc_enabled
from app.core.database import check_database_connection, get_db
from app.core.exceptions import DuplicateRequestException, IdempotencyStorageException
from app.core.idempotency import IdempotencyService, set_idempotency_service
from app.core.logger import configure_logging, get_logger
from app.core.middleware import RequestLoggingMiddleware
from app.errors import DomainError
from app.middleware.idempotency_middleware import IdempotencyMiddleware
from app.repositories.account_repository import AccountRepository
from app.schemas import EventIn
from app.services import Account, AccountService

configure_logging()
logger = get_logger(__name__)

IDEMPOTENCY_ENABLED = os.getenv("IDEMPOTENCY_ENABLED", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis_client: redis.Redis | None = None
    idempotency_service: IdempotencyService | None = None

    await check_database_connection()
    logger.info("database_connected")

    if oidc_enabled():
        get_authenticator()
        logger.info("oidc_enabled", audience=os.getenv("OIDC_AUDIENCE", ""))
    else:
        logger.warning("oidc_disabled")

    if IDEMPOTENCY_ENABLED:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await redis_client.ping()
            idempotency_service = IdempotencyService(redis_client)
            logger.info(
                "idempotency_enabled",
                redis_url=REDIS_URL.split("@")[-1],
            )
        except Exception as exc:
            logger.critical(
                "idempotency_startup_failed",
                error=str(exc),
                exc_info=True,
            )
            raise

    app.state.redis_client = redis_client
    app.state.idempotency_service = idempotency_service
    set_idempotency_service(idempotency_service)

    logger.info("application_startup", status="ready")
    try:
        yield
    finally:
        if redis_client is not None:
            await redis_client.aclose()
        set_idempotency_service(None)
        logger.info("application_shutdown", status="stopped")


app = FastAPI(title="E-Bank API", lifespan=lifespan)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RequestLoggingMiddleware)

_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "https://kalke.dev,https://www.kalke.dev,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _account_out(account: Account) -> dict[str, str | int]:
    return {"id": account.id, "balance": account.balance}


def _service(db: AsyncSession) -> AccountService:
    return AccountService(AccountRepository(db))


@app.exception_handler(DuplicateRequestException)
def handle_duplicate_request(
    request: Request,
    exc: DuplicateRequestException,
) -> JSONResponse:
    idempotency_key = getattr(request.state, "idempotency_key", exc.idempotency_key)
    get_logger("app.errors").warning(
        "duplicate_request",
        idempotency_key=idempotency_key,
        path=request.url.path,
    )
    response = JSONResponse(
        status_code=409,
        content={
            "error": "duplicate_request",
            "message": str(exc),
        },
    )
    response.headers["X-Idempotency-Key"] = idempotency_key
    response.headers["X-Idempotency-Status"] = "CONFLICT"
    return response


@app.exception_handler(IdempotencyStorageException)
def handle_idempotency_storage_error(
    request: Request,
    exc: IdempotencyStorageException,
) -> JSONResponse:
    idempotency_key = getattr(request.state, "idempotency_key", None)
    get_logger("app.errors").error(
        "idempotency.storage_error",
        idempotency_key=idempotency_key,
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    response = JSONResponse(
        status_code=503,
        content={
            "error": "idempotency_storage_unavailable",
            "message": str(exc),
        },
    )
    if idempotency_key:
        response.headers["X-Idempotency-Key"] = idempotency_key
    return response


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reset")
async def reset(
    db: AsyncSession = Depends(get_db),
    _auth: Principal | None = Depends(require_bank_write),
) -> PlainTextResponse:
    await _service(db).reset()
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/balance")
async def balance(
    account_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _auth: Principal | None = Depends(require_bank_write),
) -> PlainTextResponse:
    value = await _service(db).get_balance(account_id)
    return PlainTextResponse(content=str(value), status_code=200)


@app.post("/event")
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
