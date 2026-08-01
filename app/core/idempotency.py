from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import DuplicateRequestException, IdempotencyStorageException
from app.core.logger import get_logger, sanitize_sensitive_fields

logger = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

_idempotency_service_var: ContextVar[IdempotencyService | None] = ContextVar(
    "idempotency_service",
    default=None,
)

_HASH_EXCLUDED_KEYS = frozenset(
    {
        "timestamp",
        "request_id",
        "idempotency_key",
        "client_request_id",
        "correlation_id",
    }
)


class IdempotencyStatus(StrEnum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IdempotencyRecord:
    status: IdempotencyStatus
    request_hash: str
    response_status_code: int | None = None
    response_body: dict[str, Any] | list[Any] | str | int | float | None = None
    created_at: str = ""
    completed_at: str | None = None
    attempt_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "request_hash": self.request_hash,
            "response_status_code": self.response_status_code,
            "response_body": self.response_body,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdempotencyRecord:
        return cls(
            status=IdempotencyStatus(data["status"]),
            request_hash=data["request_hash"],
            response_status_code=data.get("response_status_code"),
            response_body=data.get("response_body"),
            created_at=data.get("created_at", ""),
            completed_at=data.get("completed_at"),
            attempt_count=int(data.get("attempt_count", 1)),
        )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_decimal(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(Decimal(value).quantize(Decimal("0.01")))
    if isinstance(value, float):
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    if isinstance(value, str):
        try:
            return str(Decimal(value).quantize(Decimal("0.01")))
        except Exception:
            return value
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    return value


_MONETARY_KEYS = frozenset({"amount", "delta_amount"})


def _canonicalize_value(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return _canonicalize_dict(value)
    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]
    if key in _MONETARY_KEYS:
        return _normalize_decimal(value)
    return value


def _canonicalize_dict(data: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key in sorted(data):
        if key in _HASH_EXCLUDED_KEYS:
            continue
        canonical[key] = _canonicalize_value(data[key], key)
    return canonical


def normalize_financial_payload(route: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _canonicalize_dict(payload)
    event_type = normalized.get("type")

    if route.endswith("/withdrawals") or (
        route == "/event" and event_type == "withdraw"
    ):
        return {
            "account_id": normalized.get("account_id") or normalized.get("origin"),
            "amount": _normalize_decimal(normalized.get("amount")),
            "currency": normalized.get("currency", "BRL"),
            "destination_account": normalized.get("destination_account")
            or normalized.get("destination"),
        }

    if route.endswith("/deposits") or (route == "/event" and event_type == "deposit"):
        return {
            "account_id": normalized.get("account_id") or normalized.get("destination"),
            "amount": _normalize_decimal(normalized.get("amount")),
            "currency": normalized.get("currency", "BRL"),
            "source_reference": normalized.get("source_reference"),
        }

    if "/accounts/" in route and route.endswith("/balance"):
        return {
            "account_id": normalized.get("account_id"),
            "delta_amount": _normalize_decimal(
                normalized.get("delta_amount") or normalized.get("amount")
            ),
            "operation_type": normalized.get("operation_type"),
        }

    if route == "/event" and event_type == "transfer":
        return {
            "type": "transfer",
            "origin": normalized.get("origin"),
            "destination": normalized.get("destination"),
            "amount": _normalize_decimal(normalized.get("amount")),
            "currency": normalized.get("currency", "BRL"),
        }

    return normalized


def compute_request_hash(
    route: str,
    method: str,
    user_id: str,
    payload: dict[str, Any],
) -> str:
    canonical_payload = normalize_financial_payload(route, payload)
    serialized = json.dumps(
        {
            "route": route,
            "method": method.upper(),
            "user_id": user_id,
            "payload": canonical_payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


class IdempotencyService:
    def __init__(
        self,
        redis_client: Redis,
        ttl_processing: int = 30,
        ttl_completed: int = 86400,
    ) -> None:
        self._redis = redis_client
        self._ttl_processing = ttl_processing
        self._ttl_completed = ttl_completed

    @property
    def redis_client(self) -> Redis:
        return self._redis

    async def generate_key(
        self,
        route: str,
        method: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> str:
        request_hash = compute_request_hash(route, method, user_id, payload)
        return f"idempotency:{route}:{user_id}:{request_hash}"

    async def check(self, key: str) -> IdempotencyRecord | None:
        try:
            raw = await self._redis.get(key)
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc

        if raw is None:
            return None

        if isinstance(raw, bytes):
            raw = raw.decode()

        return IdempotencyRecord.from_dict(json.loads(raw))

    async def set_processing(self, key: str, request_hash: str) -> None:
        record = IdempotencyRecord(
            status=IdempotencyStatus.PROCESSING,
            request_hash=request_hash,
            created_at=_utc_now_iso(),
            attempt_count=1,
        )
        try:
            created = await self._redis.set(
                key,
                json.dumps(record.to_dict()),
                nx=True,
                ex=self._ttl_processing,
            )
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc

        if not created:
            raise DuplicateRequestException(key)

    async def set_completed(
        self,
        key: str,
        status_code: int,
        response_body: dict[str, Any] | list[Any] | str | float | None,
    ) -> None:
        existing = await self.check(key)
        attempt_count = existing.attempt_count if existing else 1
        sanitized_body: dict[str, Any] | list[Any] | str | int | float | None
        if isinstance(response_body, dict):
            sanitized_body = sanitize_sensitive_fields(response_body)
        else:
            sanitized_body = response_body

        record = IdempotencyRecord(
            status=IdempotencyStatus.COMPLETED,
            request_hash=existing.request_hash if existing else "",
            response_status_code=status_code,
            response_body=sanitized_body,
            created_at=existing.created_at if existing else _utc_now_iso(),
            completed_at=_utc_now_iso(),
            attempt_count=attempt_count,
        )
        try:
            await self._redis.set(
                key,
                json.dumps(record.to_dict()),
                ex=self._ttl_completed,
            )
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc

    async def mark_failed(self, key: str) -> None:
        existing = await self.check(key)
        record = IdempotencyRecord(
            status=IdempotencyStatus.FAILED,
            request_hash=existing.request_hash if existing else "",
            created_at=existing.created_at if existing else _utc_now_iso(),
            attempt_count=existing.attempt_count if existing else 1,
        )
        try:
            await self._redis.set(
                key,
                json.dumps(record.to_dict()),
                ex=self._ttl_processing,
            )
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc

    async def set_failed(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc

    async def increment_attempt(self, key: str) -> None:
        record = await self.check(key)
        if record is None:
            return

        updated = IdempotencyRecord(
            status=record.status,
            request_hash=record.request_hash,
            response_status_code=record.response_status_code,
            response_body=record.response_body,
            created_at=record.created_at,
            completed_at=record.completed_at,
            attempt_count=record.attempt_count + 1,
        )
        ttl = (
            self._ttl_completed
            if record.status == IdempotencyStatus.COMPLETED
            else self._ttl_processing
        )
        try:
            await self._redis.set(key, json.dumps(updated.to_dict()), ex=ttl)
        except RedisError as exc:
            raise IdempotencyStorageException(str(exc)) from exc


def set_idempotency_service(service: IdempotencyService | None) -> None:
    _idempotency_service_var.set(service)


def get_idempotency_service() -> IdempotencyService:
    service = _idempotency_service_var.get()
    if service is None:
        raise IdempotencyStorageException("Idempotency service is not configured")
    return service


def idempotent(
    ttl: int = 86400,
    *,
    route: str,
    user_id_param: str = "account_id",
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorator(
        func: Callable[P, Awaitable[T]],
    ) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            service = get_idempotency_service()
            bound = dict(zip(func.__code__.co_varnames[: len(args)], args))
            bound.update(kwargs)
            user_id = str(bound.get(user_id_param, "anonymous"))
            payload = {
                key: value
                for key, value in bound.items()
                if key not in {"self", "cls"} and not callable(value)
            }
            payload = normalize_financial_payload(route, payload)
            key = await service.generate_key(route, "POST", user_id, payload)
            structlog.contextvars.bind_contextvars(idempotency_key=key)

            record = await service.check(key)
            if record and record.status == IdempotencyStatus.COMPLETED:
                logger.info(
                    "idempotency.hit",
                    idempotency_key=key,
                    route=route,
                    user_id=user_id,
                    attempt_count=record.attempt_count,
                )
                if isinstance(record.response_body, dict):
                    return record.response_body  # type: ignore[return-value]
                raise IdempotencyStorageException(
                    "Cached decorator response is invalid"
                )

            if record and record.status == IdempotencyStatus.PROCESSING:
                logger.warning(
                    "idempotency.processing_conflict",
                    idempotency_key=key,
                    route=route,
                    user_id=user_id,
                    attempt_count=record.attempt_count,
                )
                raise DuplicateRequestException(key)

            if record and record.status == IdempotencyStatus.FAILED:
                await service.set_failed(key)
                logger.warning(
                    "idempotency.failed_cleared",
                    idempotency_key=key,
                    route=route,
                    user_id=user_id,
                    attempt_count=record.attempt_count,
                )

            request_hash = compute_request_hash(route, "POST", user_id, payload)
            await service.set_processing(key, request_hash)
            logger.info(
                "idempotency.miss",
                idempotency_key=key,
                route=route,
                user_id=user_id,
                attempt_count=1,
            )

            try:
                result = await func(*args, **kwargs)
            except Exception:
                await service.set_failed(key)
                raise

            response_body: dict[str, Any]
            if isinstance(result, dict):
                response_body = result
            else:
                response_body = {"result": result}

            completion_service = IdempotencyService(
                service.redis_client,
                ttl_processing=service._ttl_processing,
                ttl_completed=ttl,
            )
            await completion_service.set_completed(key, 200, response_body)
            return result

        return wrapper

    return decorator
