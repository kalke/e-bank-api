from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from app.core.config import get_settings

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

# Bound in configure_logging() after secrets + settings are available.
_SERVICE_NAME = "e-bank-api"
_ENVIRONMENT = "development"


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


def _add_app_context(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    event_dict.setdefault("environment", _ENVIRONMENT)
    event_dict.setdefault("service", _SERVICE_NAME)
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
    global _SERVICE_NAME, _ENVIRONMENT

    settings = get_settings()
    _SERVICE_NAME = settings.service_name
    _ENVIRONMENT = settings.env.lower()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    renderer: Processor
    if settings.use_json_logs:
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
