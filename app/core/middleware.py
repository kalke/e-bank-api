from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logger import get_logger
from app.domain.ids import new_uuid

RequestCallNext = Callable[[Request], Awaitable[Response]]

_SKIP_PATHS = frozenset({"/health", "/ready", "/metrics"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestCallNext) -> Response:
        incoming = (request.headers.get("x-request-id") or "").strip()
        request_id = incoming or new_uuid()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id

        logger = get_logger("http")
        start = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if request.url.path not in _SKIP_PATHS:
                self._log_response(
                    logger,
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                    request_id,
                )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "http.request",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
                outcome="error",
                error_code="unhandled",
                exc_info=True,
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _log_response(
        logger: structlog.stdlib.BoundLogger,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_id: str,
    ) -> None:
        outcome = "ok" if status_code < 400 else "error"
        payload = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
            "outcome": outcome,
        }
        if status_code >= 500:
            logger.error("http.request", **payload)
        elif status_code >= 400:
            logger.warning("http.request", **payload)
        else:
            logger.info("http.request", **payload)
