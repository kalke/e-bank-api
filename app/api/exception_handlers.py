from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import DuplicateRequestException, IdempotencyStorageException
from app.core.logger import get_logger
from app.core.rate_limit import RateLimitExceeded
from app.errors import DomainError


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


def handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    response = JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "message": str(exc)},
    )
    response.headers["Retry-After"] = str(exc.retry_after)
    return response


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


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(
        DuplicateRequestException,
        handle_duplicate_request,
    )
    application.add_exception_handler(
        IdempotencyStorageException,
        handle_idempotency_storage_error,
    )
    application.add_exception_handler(RateLimitExceeded, handle_rate_limit)
    application.add_exception_handler(DomainError, handle_domain_error)
    application.add_exception_handler(Exception, handle_unhandled_exception)
