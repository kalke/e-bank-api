import logging

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.middleware import RequestLoggingMiddleware
from app.errors import AccountNotFound, DomainError
from app.main import handle_domain_error, handle_unhandled_exception


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


class TestExceptionHandlers:
    def test_domain_error_handler_logs_warning(self) -> None:
        app = FastAPI()
        app.add_exception_handler(DomainError, handle_domain_error)

        @app.get("/not-found")
        def not_found() -> None:
            raise AccountNotFound("100")

        client = TestClient(app, raise_server_exceptions=False)

        with capture_logs() as logs:
            response = client.get("/not-found")

        assert response.status_code == 404
        domain_logs = [e for e in logs if e.get("event") == "domain_error"]
        assert len(domain_logs) == 1
        assert domain_logs[0]["log_level"] == "warning"
        assert domain_logs[0]["status_code"] == 404

    def test_unhandled_exception_handler_logs_error(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)
        app.add_exception_handler(Exception, handle_unhandled_exception)

        @app.get("/boom")
        def boom() -> None:
            raise RuntimeError("unexpected failure")

        client = TestClient(app, raise_server_exceptions=False)

        with capture_logs() as logs:
            response = client.get("/boom")

        assert response.status_code == 500
        assert response.json() == {"message": "Internal server error"}
        unhandled = [e for e in logs if e.get("event") == "unhandled_exception"]
        assert len(unhandled) == 1
        assert unhandled[0]["log_level"] == "error"
        assert unhandled[0]["request_id"]
