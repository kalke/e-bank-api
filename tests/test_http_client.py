import logging

import httpx
import pytest
import structlog
from structlog.testing import capture_logs

from app.core.http_client import LoggedHttpClient


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    structlog.reset_defaults()
    structlog.configure(
        processors=[structlog.processors.dict_tracebacks],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    yield
    structlog.reset_defaults()


class TestLoggedHttpClient:
    def test_logs_successful_external_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        client = LoggedHttpClient(httpx.Client(transport=transport))

        with capture_logs() as logs:
            response = client.get("https://api.example.com/data")

        assert response.status_code == 200
        external = [e for e in logs if e.get("event") == "external_request"]
        assert len(external) == 1
        assert external[0]["log_level"] == "info"
        assert external[0]["method"] == "GET"
        assert external[0]["status_code"] == 200
        assert "duration_ms" in external[0]

    def test_logs_warning_for_client_error_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        client = LoggedHttpClient(httpx.Client(transport=transport))

        with capture_logs() as logs:
            response = client.get("https://api.example.com/missing")

        assert response.status_code == 404
        external = [e for e in logs if e.get("event") == "external_request"]
        assert external[0]["log_level"] == "warning"

    def test_logs_error_for_failed_external_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        transport = httpx.MockTransport(handler)
        client = LoggedHttpClient(httpx.Client(transport=transport))

        with capture_logs() as logs, pytest.raises(httpx.ConnectError):
            client.get("https://api.example.com/down")

        failed = [e for e in logs if e.get("event") == "external_request_failed"]
        assert len(failed) == 1
        assert failed[0]["log_level"] == "error"

    def test_redacts_sensitive_query_params_in_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        client = LoggedHttpClient(httpx.Client(transport=transport))

        with capture_logs() as logs:
            client.get("https://api.example.com/auth?token=secret-value")

        external = [e for e in logs if e.get("event") == "external_request"]
        assert external[0]["url"] == "https://api.example.com/auth?[REDACTED]"
