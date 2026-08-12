from __future__ import annotations

import json
import os
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.oidc import (
    HEADER_FORWARD_SECRET,
    HEADER_USER_EMAIL,
    HEADER_USER_SUB,
    AuthError,
    get_authenticator,
    oidc_enabled,
    resolve_effective_principal,
)
from app.core.exceptions import DuplicateRequestException, IdempotencyStorageException
from app.core.idempotency import (
    IdempotencyRecord,
    IdempotencyService,
    IdempotencyStatus,
    compute_request_hash,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH"})
DEFAULT_EXCLUDE_PATHS = "/health,/metrics"


def get_excluded_paths() -> frozenset[str]:
    try:
        from app.core.config import get_settings

        raw = get_settings().idempotency_exclude_paths
    except Exception:
        raw = os.getenv("IDEMPOTENCY_EXCLUDE_PATHS", DEFAULT_EXCLUDE_PATHS)
    return frozenset(path.strip() for path in raw.split(",") if path.strip())


def extract_user_id(request: Request, payload: dict[str, Any]) -> str | None:
    """Use authenticated subject only — never body-derived account fields."""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return str(user_id)
    principal = getattr(request.state, "principal", None)
    if principal is not None and getattr(principal, "subject", None):
        return str(principal.subject)
    _ = payload
    if not oidc_enabled() or get_authenticator() is None:
        return None
    header = request.headers.get("Authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    try:
        resolved = resolve_effective_principal(
            token,
            {
                HEADER_FORWARD_SECRET: request.headers.get(HEADER_FORWARD_SECRET) or "",
                HEADER_USER_SUB: request.headers.get(HEADER_USER_SUB) or "",
                HEADER_USER_EMAIL: request.headers.get(HEADER_USER_EMAIL) or "",
            },
        )
    except AuthError:
        return None
    request.state.user_id = resolved.subject
    request.state.principal = resolved
    return resolved.subject


def _parse_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {"_raw": parsed}


async def _read_response_bytes(response: Response) -> bytes:
    body = getattr(response, "body", None)
    if body:
        if isinstance(body, memoryview):
            return body.tobytes()
        if isinstance(body, bytes):
            return body

    chunks: list[bytes] = []
    if hasattr(response, "body_iterator"):
        async for chunk in response.body_iterator:
            if isinstance(chunk, memoryview):
                chunks.append(chunk.tobytes())
            elif isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(str(chunk).encode())
    return b"".join(chunks)


def _parse_response_bytes(body: bytes) -> dict[str, Any] | list[Any] | str | None:
    if not body:
        return None
    try:
        return json.loads(body.decode())
    except json.JSONDecodeError:
        return body.decode()


def _rebuild_response(response: Response, body: bytes) -> Response:
    headers = dict(response.headers)
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        body = await request.body()
        skip_response = await self._maybe_skip(request, call_next, body)
        if skip_response is not None:
            return skip_response

        service: IdempotencyService = request.app.state.idempotency_service
        payload = _parse_body(body)
        user_id = extract_user_id(request, payload)
        assert user_id is not None

        route = request.url.path
        method = request.method
        idempotency_key = await self._generate_key_or_error(
            service,
            route,
            method,
            user_id,
            payload,
        )
        if isinstance(idempotency_key, JSONResponse):
            return idempotency_key

        structlog.contextvars.bind_contextvars(idempotency_key=idempotency_key)
        request.state.idempotency_key = idempotency_key

        cached = await self._resolve_existing_record(
            service,
            idempotency_key,
            route,
            user_id,
        )
        if cached is not None:
            return cached

        lock_error = await self._acquire_processing_lock(
            service,
            idempotency_key,
            route,
            method,
            user_id,
            payload,
        )
        if lock_error is not None:
            return lock_error

        logger.info(
            "idempotency.miss",
            idempotency_key=idempotency_key,
            route=route,
            user_id=user_id,
            attempt_count=1,
        )

        return await self._execute_and_cache(
            request,
            call_next,
            service,
            body,
            idempotency_key,
            route,
            user_id,
        )

    async def _maybe_skip(
        self,
        request: Request,
        call_next: Any,
        body: bytes,
    ) -> Response | None:
        if request.method not in MUTATING_METHODS:
            return await call_next(request)

        if request.url.path in get_excluded_paths():
            return await call_next(request)

        service: IdempotencyService | None = getattr(
            request.app.state,
            "idempotency_service",
            None,
        )
        if service is None:
            return await call_next(request)

        payload = _parse_body(body)
        if extract_user_id(request, payload) is None:
            return await call_next(self._rebuild_request(request, body))

        return None

    async def _generate_key_or_error(
        self,
        service: IdempotencyService,
        route: str,
        method: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> str | JSONResponse:
        try:
            return await service.generate_key(route, method, user_id, payload)
        except IdempotencyStorageException as exc:
            return self._storage_error_response(exc, route, user_id)

    async def _resolve_existing_record(
        self,
        service: IdempotencyService,
        idempotency_key: str,
        route: str,
        user_id: str,
    ) -> JSONResponse | None:
        try:
            record = await service.check(idempotency_key)
        except IdempotencyStorageException as exc:
            return self._storage_error_response(
                exc,
                route,
                user_id,
                idempotency_key,
            )

        if record is None:
            return None

        if record.status == IdempotencyStatus.COMPLETED:
            logger.info(
                "idempotency.hit",
                idempotency_key=idempotency_key,
                route=route,
                user_id=user_id,
                attempt_count=record.attempt_count,
            )
            return self._cached_response(idempotency_key, record)

        if record.status == IdempotencyStatus.PROCESSING:
            return self._log_and_duplicate(idempotency_key, route, user_id, record)

        if record.status == IdempotencyStatus.FAILED:
            return await self._clear_failed_record(
                service,
                idempotency_key,
                route,
                user_id,
                record,
            )

        return None

    async def _clear_failed_record(
        self,
        service: IdempotencyService,
        idempotency_key: str,
        route: str,
        user_id: str,
        record: IdempotencyRecord,
    ) -> JSONResponse | None:
        try:
            await service.set_failed(idempotency_key)
        except IdempotencyStorageException as exc:
            return self._storage_error_response(
                exc,
                route,
                user_id,
                idempotency_key,
            )

        logger.warning(
            "idempotency.failed_cleared",
            idempotency_key=idempotency_key,
            route=route,
            user_id=user_id,
            attempt_count=record.attempt_count,
        )
        return None

    async def _acquire_processing_lock(
        self,
        service: IdempotencyService,
        idempotency_key: str,
        route: str,
        method: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> JSONResponse | None:
        request_hash = compute_request_hash(route, method, user_id, payload)
        try:
            await service.set_processing(idempotency_key, request_hash)
        except DuplicateRequestException:
            return self._log_and_duplicate(idempotency_key, route, user_id)
        except IdempotencyStorageException as exc:
            return self._storage_error_response(
                exc,
                route,
                user_id,
                idempotency_key,
            )
        return None

    async def _execute_and_cache(
        self,
        request: Request,
        call_next: Any,
        service: IdempotencyService,
        body: bytes,
        idempotency_key: str,
        route: str,
        user_id: str,
    ) -> Response:
        rebuilt_request = self._rebuild_request(request, body)
        try:
            response = await call_next(rebuilt_request)
        except Exception:
            storage_error = await self._clear_on_handler_failure(
                service,
                idempotency_key,
                route,
                user_id,
            )
            if storage_error is not None:
                return storage_error
            raise

        raw_body = await _read_response_bytes(response)
        response_body = _parse_response_bytes(raw_body)
        try:
            await service.set_completed(
                idempotency_key,
                response.status_code,
                response_body,
            )
        except IdempotencyStorageException as exc:
            return self._storage_error_response(
                exc,
                route,
                user_id,
                idempotency_key,
            )

        rebuilt_response = _rebuild_response(response, raw_body)
        rebuilt_response.headers["X-Idempotency-Key"] = idempotency_key
        rebuilt_response.headers["X-Idempotency-Status"] = "MISS"
        return rebuilt_response

    async def _clear_on_handler_failure(
        self,
        service: IdempotencyService,
        idempotency_key: str,
        route: str,
        user_id: str,
    ) -> JSONResponse | None:
        try:
            await service.set_failed(idempotency_key)
        except IdempotencyStorageException as exc:
            return self._storage_error_response(
                exc,
                route,
                user_id,
                idempotency_key,
            )
        return None

    def _log_and_duplicate(
        self,
        idempotency_key: str,
        route: str,
        user_id: str,
        record: IdempotencyRecord | None = None,
    ) -> JSONResponse:
        logger.warning(
            "idempotency.processing_conflict",
            idempotency_key=idempotency_key,
            route=route,
            user_id=user_id,
            attempt_count=record.attempt_count if record else 1,
        )
        return self._duplicate_response(idempotency_key)

    @staticmethod
    def _rebuild_request(request: Request, body: bytes) -> Request:
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(request.scope, receive)

    @staticmethod
    def _cached_response(idempotency_key: str, record: Any) -> JSONResponse:
        body = record.response_body if record.response_body is not None else {}
        if not isinstance(body, (dict, list)):
            body = {"message": str(body)}
        response = JSONResponse(
            status_code=record.response_status_code or 200,
            content=body,
        )
        response.headers["X-Idempotency-Key"] = idempotency_key
        response.headers["X-Idempotency-Status"] = "HIT"
        return response

    @staticmethod
    def _duplicate_response(idempotency_key: str) -> JSONResponse:
        response = JSONResponse(
            status_code=409,
            content={
                "error": "duplicate_request",
                "message": "A request with this key is already being processed",
            },
        )
        response.headers["X-Idempotency-Key"] = idempotency_key
        response.headers["X-Idempotency-Status"] = "CONFLICT"
        return response

    @staticmethod
    def _storage_error_response(
        exc: IdempotencyStorageException,
        route: str,
        user_id: str | None,
        idempotency_key: str | None = None,
    ) -> JSONResponse:
        logger.error(
            "idempotency.storage_error",
            idempotency_key=idempotency_key,
            route=route,
            user_id=user_id,
            error=str(exc),
            exc_info=True,
        )
        response = JSONResponse(
            status_code=503,
            content={
                "error": "idempotency_storage_unavailable",
                "message": "Idempotency storage is unavailable",
            },
        )
        if idempotency_key:
            response.headers["X-Idempotency-Key"] = idempotency_key
        return response
