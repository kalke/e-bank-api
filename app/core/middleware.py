from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logger import get_logger

RequestCallNext = Callable[[Request], Awaitable[Response]]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestCallNext) -> Response:
        request_id = str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id

        logger = get_logger("http.request")
        start = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
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
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
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
        payload = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
        }

        if status_code >= 500:
            logger.error("request_completed", **payload)
        elif status_code >= 400:
            logger.warning("request_completed", **payload)
        else:
            logger.info("request_completed", **payload)
