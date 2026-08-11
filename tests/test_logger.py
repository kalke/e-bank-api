import json
import logging

import pytest
import structlog
from structlog.testing import capture_logs

from app.core.config import get_settings
from app.core.logger import (
    configure_logging,
    get_logger,
    sanitize_sensitive_fields,
)


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    structlog.reset_defaults()
    get_settings.cache_clear()
    yield
    structlog.reset_defaults()
    get_settings.cache_clear()


class TestSanitizeSensitiveFields:
    def test_redacts_top_level_sensitive_keys(self) -> None:
        data = {
            "username": "alice",
            "password": "secret123",
            "token": "abc",
            "authorization": "Bearer xyz",
        }
        result = sanitize_sensitive_fields(data)
        assert result["username"] == "alice"
        assert result["password"] == "***REDACTED***"
        assert result["token"] == "***REDACTED***"
        assert result["authorization"] == "***REDACTED***"

    def test_redacts_nested_sensitive_keys(self) -> None:
        data = {"user": {"cpf": "12345678900", "name": "Alice"}}
        result = sanitize_sensitive_fields(data)
        assert result["user"]["cpf"] == "***REDACTED***"
        assert result["user"]["name"] == "Alice"

    def test_redacts_card_number_and_secret(self) -> None:
        data = {"card_number": "4111111111111111", "secret": "s3cr3t"}
        result = sanitize_sensitive_fields(data)
        assert result["card_number"] == "***REDACTED***"
        assert result["secret"] == "***REDACTED***"


class TestLoggerConfiguration:
    def test_production_logs_json_with_required_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("SERVICE_NAME", "e-bank-api")
        get_settings.cache_clear()
        configure_logging()
        service = get_settings().service_name

        def add_context(
            _logger: logging.Logger, _method: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            event_dict.setdefault("logger_name", "test.logger")
            event_dict.setdefault("environment", "production")
            event_dict.setdefault("service", service)
            return event_dict

        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            add_context,
        ]

        with capture_logs(processors=processors) as cap:
            get_logger("test.logger").info("test_event", request_id="req-123")

        assert len(cap) == 1
        entry = cap[0]
        assert entry["event"] == "test_event"
        assert entry["log_level"] == "info"
        assert entry["timestamp"]
        assert entry["environment"] == "production"
        assert entry["service"] == service
        assert entry["request_id"] == "req-123"

        rendered = json.loads(
            structlog.processors.JSONRenderer()(None, None, dict(entry))
        )
        assert rendered["event"] == "test_event"
        assert rendered["level"] == "info"

    def test_development_configure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LOG_FORMAT", "text")
        get_settings.cache_clear()
        configure_logging()
        log = get_logger("test.dev")
        log.debug("dev_event", detail="ok")

    def test_log_format_json_overrides_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("LOG_FORMAT", "json")
        get_settings.cache_clear()
        assert get_settings().use_json_logs is True
