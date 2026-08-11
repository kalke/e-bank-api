from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import Processor

SERVICE_NAME = os.getenv("SERVICE_NAME", "e-bank-api")
ENVIRONMENT = os.getenv("ENV", "development").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "").strip().lower()

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "authorization",
        "secret",
        "card_number",
        "cpf",
        "cnpj",
        "otp",
        "code",
    }
)

_REDACTED = "***REDACTED***"


def sanitize_sensitive_fields(data: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = _REDACTED
        elif isinstance(value, dict):
            sanitized[key] = sanitize_sensitive_fields(value)
        else:
            sanitized[key] = value
    return sanitized


def _use_json_logs() -> bool:
    if LOG_FORMAT in {"json", "text"}:
        return LOG_FORMAT == "json"
    return ENVIRONMENT in {"production", "prod"}


def _add_app_context(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    event_dict.setdefault("environment", ENVIRONMENT)
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def _pre_chain_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        _add_app_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    renderer: Processor
    if _use_json_logs():
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_pre_chain_processors(),
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
