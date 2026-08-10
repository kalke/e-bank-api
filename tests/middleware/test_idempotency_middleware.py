import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.idempotency import IdempotencyService
from app.middleware.idempotency_middleware import IdempotencyMiddleware


class FakeAuthMiddleware(BaseHTTPMiddleware):
    """Simulate auth deps setting request.state.user_id from X-Test-User."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-Test-User", "user-a")
        return await call_next(request)


@pytest.fixture
def idempotency_app() -> FastAPI:
    import fakeredis.aioredis

    app = FastAPI()
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.idempotency_service = IdempotencyService(fake_redis)
    # Starlette: last added runs first on the request. FakeAuth must be outer so
    # request.state.user_id is set before IdempotencyMiddleware runs.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(FakeAuthMiddleware)

    handler_calls = {"count": 0}

    @app.post("/event")
    async def create_event(payload: dict = Body(...)) -> JSONResponse:
        handler_calls["count"] += 1
        return JSONResponse(
            status_code=201,
            content={"destination": {"id": payload["destination"], "balance": 10}},
        )

    @app.post("/health")
    async def health_post() -> JSONResponse:
        handler_calls["count"] += 1
        return JSONResponse(status_code=200, content={"status": "ok"})

    app.state.handler_calls = handler_calls
    return app


@pytest.fixture
def client(idempotency_app: FastAPI) -> TestClient:
    return TestClient(idempotency_app)


class TestIdempotencyMiddleware:
    def test_same_payload_returns_cached_response_without_second_handler_call(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
    ) -> None:
        body = {"type": "deposit", "destination": "100", "amount": 10}

        first = client.post("/event", json=body)
        second = client.post("/event", json=body)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json() == second.json()
        assert first.headers["X-Idempotency-Status"] == "MISS"
        assert second.headers["X-Idempotency-Status"] == "HIT"
        assert first.headers["X-Idempotency-Key"] == second.headers["X-Idempotency-Key"]
        assert idempotency_app.state.handler_calls["count"] == 1

    def test_float_variants_are_treated_as_same_request(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
    ) -> None:
        first = client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 100.0},
        )
        second = client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 100.00},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.headers["X-Idempotency-Status"] == "HIT"
        assert idempotency_app.state.handler_calls["count"] == 1

    def test_processing_state_returns_409(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
    ) -> None:
        service: IdempotencyService = idempotency_app.state.idempotency_service
        body = {"type": "deposit", "destination": "200", "amount": 15}

        async def lock() -> None:
            key = await service.generate_key("/event", "POST", "user-a", body)
            await service.set_processing(key, "locked")

        asyncio.run(lock())

        response = client.post("/event", json=body)
        assert response.status_code == 409
        assert response.json()["error"] == "duplicate_request"
        assert response.headers["X-Idempotency-Status"] == "CONFLICT"
        assert idempotency_app.state.handler_calls["count"] == 0

    def test_failed_state_is_cleared_and_request_reprocessed(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
    ) -> None:
        service: IdempotencyService = idempotency_app.state.idempotency_service
        body = {"type": "deposit", "destination": "300", "amount": 20}

        async def seed_failed() -> None:
            key = await service.generate_key("/event", "POST", "user-a", body)
            await service.set_processing(key, "hash")
            await service.mark_failed(key)

        asyncio.run(seed_failed())

        response = client.post("/event", json=body)
        assert response.status_code == 201
        assert response.headers["X-Idempotency-Status"] == "MISS"
        assert idempotency_app.state.handler_calls["count"] == 1

    def test_redis_down_returns_503(self, idempotency_app: FastAPI) -> None:
        broken = AsyncMock()
        broken.get.side_effect = RedisError("connection refused")
        broken.set.side_effect = RedisError("connection refused")
        idempotency_app.state.idempotency_service = IdempotencyService(broken)

        with TestClient(
            idempotency_app, raise_server_exceptions=False
        ) as failing_client:
            response = failing_client.post(
                "/event",
                json={"type": "deposit", "destination": "400", "amount": 5},
            )

        assert response.status_code == 503
        assert response.json()["error"] == "idempotency_storage_unavailable"

    def test_excluded_path_skips_idempotency(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("IDEMPOTENCY_EXCLUDE_PATHS", "/health,/metrics")

        first = client.post("/health")
        second = client.post("/health")

        assert first.status_code == 200
        assert second.status_code == 200
        assert "X-Idempotency-Key" not in first.headers
        assert idempotency_app.state.handler_calls["count"] == 2

    def test_different_user_id_generates_different_keys(
        self,
        client: TestClient,
        idempotency_app: FastAPI,
    ) -> None:
        body = {"type": "deposit", "destination": "500", "amount": 8}
        first = client.post("/event", json=body, headers={"X-Test-User": "alice"})
        second = client.post("/event", json=body, headers={"X-Test-User": "bob"})

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.headers["X-Idempotency-Key"] != second.headers["X-Idempotency-Key"]
        assert idempotency_app.state.handler_calls["count"] == 2
