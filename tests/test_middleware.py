import logging

import pytest
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.middleware import RequestLoggingMiddleware


@pytest.fixture
def logging_client() -> TestClient:
    structlog.reset_defaults()
    structlog.configure(
        processors=[structlog.processors.dict_tracebacks],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )

    test_app = FastAPI()
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/missing")
    def missing() -> JSONResponse:
        return JSONResponse(status_code=404, content={"message": "not found"})

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client

    structlog.reset_defaults()


class TestRequestLoggingMiddleware:
    def test_logs_info_for_successful_request(self, logging_client: TestClient) -> None:
        with capture_logs() as logs:
            response = logging_client.get("/ok")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        completed = [e for e in logs if e.get("event") == "http.request"]
        assert len(completed) == 1
        assert completed[0]["log_level"] == "info"
        assert completed[0]["method"] == "GET"
        assert completed[0]["path"] == "/ok"
        assert completed[0]["status_code"] == 200
        assert completed[0]["outcome"] == "ok"
        assert completed[0]["request_id"] == response.headers["X-Request-ID"]

    def test_logs_warning_for_client_error(self, logging_client: TestClient) -> None:
        with capture_logs() as logs:
            response = logging_client.get("/missing")

        assert response.status_code == 404
        completed = [e for e in logs if e.get("event") == "http.request"]
        assert len(completed) == 1
        assert completed[0]["log_level"] == "warning"
        assert completed[0]["status_code"] == 404
        assert completed[0]["outcome"] == "error"
        assert completed[0]["request_id"]
