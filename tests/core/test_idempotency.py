import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError

from app.core.exceptions import DuplicateRequestException, IdempotencyStorageException
from app.core.idempotency import (
    IdempotencyService,
    IdempotencyStatus,
    compute_request_hash,
    normalize_financial_payload,
)


@pytest.fixture
def fake_redis() -> AsyncMock:
    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def idempotency_service(fake_redis: AsyncMock) -> IdempotencyService:
    return IdempotencyService(fake_redis)


class TestPayloadHashing:
    def test_float_and_decimal_string_produce_same_hash(self) -> None:
        payload_a = {
            "type": "deposit",
            "destination": "100",
            "amount": 100.0,
        }
        payload_b = {
            "type": "deposit",
            "destination": "100",
            "amount": 100.00,
        }
        hash_a = compute_request_hash("/event", "POST", "usr_1", payload_a)
        hash_b = compute_request_hash("/event", "POST", "usr_1", payload_b)
        assert hash_a == hash_b

    def test_different_user_id_produces_different_key(
        self,
        idempotency_service: IdempotencyService,
    ) -> None:
        payload = {"type": "deposit", "destination": "100", "amount": 10}

        async def run() -> tuple[str, str]:
            key_a = await idempotency_service.generate_key(
                "/event",
                "POST",
                "usr_a",
                payload,
            )
            key_b = await idempotency_service.generate_key(
                "/event",
                "POST",
                "usr_b",
                payload,
            )
            return key_a, key_b

        key_a, key_b = asyncio.run(run())
        assert key_a != key_b

    def test_withdrawal_normalization_uses_decimal_places(self) -> None:
        normalized = normalize_financial_payload(
            "/event",
            {
                "type": "withdraw",
                "origin": "100",
                "amount": 50,
                "currency": "BRL",
            },
        )
        assert normalized["amount"] == "50.00"
        assert normalized["account_id"] == "100"


class TestIdempotencyService:
    def test_set_processing_uses_nx_lock(
        self,
        idempotency_service: IdempotencyService,
    ) -> None:
        key = "idempotency:/event:usr_1:abc"

        async def run() -> None:
            await idempotency_service.set_processing(key, "hash-1")
            with pytest.raises(DuplicateRequestException):
                await idempotency_service.set_processing(key, "hash-1")

        asyncio.run(run())

    def test_completed_record_is_returned_by_check(
        self,
        idempotency_service: IdempotencyService,
    ) -> None:
        key = "idempotency:/event:usr_1:completed"

        async def run() -> None:
            await idempotency_service.set_processing(key, "hash-1")
            await idempotency_service.set_completed(
                key,
                201,
                {"destination": {"id": "100", "balance": 10}},
            )
            record = await idempotency_service.check(key)
            assert record is not None
            assert record.status == IdempotencyStatus.COMPLETED
            assert record.response_status_code == 201
            assert record.response_body == {
                "destination": {"id": "100", "balance": 10},
            }

        asyncio.run(run())

    def test_set_failed_deletes_key(
        self,
        idempotency_service: IdempotencyService,
    ) -> None:
        key = "idempotency:/event:usr_1:failed"

        async def run() -> None:
            await idempotency_service.set_processing(key, "hash-1")
            await idempotency_service.mark_failed(key)
            record = await idempotency_service.check(key)
            assert record is not None
            assert record.status == IdempotencyStatus.FAILED
            await idempotency_service.set_failed(key)
            assert await idempotency_service.check(key) is None

        asyncio.run(run())

    def test_redis_failure_raises_storage_exception(self) -> None:
        broken_redis = AsyncMock()
        broken_redis.get.side_effect = RedisError("down")
        service = IdempotencyService(broken_redis)

        async def run() -> None:
            with pytest.raises(IdempotencyStorageException):
                await service.check("idempotency:/event:usr_1:broken")

        asyncio.run(run())

    def test_completed_response_is_sanitized(
        self,
        idempotency_service: IdempotencyService,
    ) -> None:
        key = "idempotency:/event:usr_1:sensitive"

        async def run() -> None:
            await idempotency_service.set_processing(key, "hash-1")
            await idempotency_service.set_completed(
                key,
                200,
                {"token": "secret-token", "balance": 10},
            )
            record = await idempotency_service.check(key)
            assert record is not None
            body = record.response_body
            assert isinstance(body, dict)
            assert body["token"] == "***REDACTED***"
            assert body["balance"] == 10

        asyncio.run(run())

    def test_increment_attempt_updates_record(
        self,
        idempotency_service: IdempotencyService,
        fake_redis: AsyncMock,
    ) -> None:
        key = "idempotency:/event:usr_1:attempt"

        async def run() -> None:
            await idempotency_service.set_processing(key, "hash-1")
            await idempotency_service.increment_attempt(key)
            raw = await fake_redis.get(key)
            data = json.loads(raw)
            assert data["attempt_count"] == 2

        asyncio.run(run())
