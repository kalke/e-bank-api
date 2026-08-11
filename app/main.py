from app.core.secrets import load_secrets_into_env

# Secrets before settings/logging/database imports (same contract as kalke-auth).
load_secrets_into_env()

from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import redis.asyncio as redis  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api import demo as demo_api  # noqa: E402
from app.api import health as health_api  # noqa: E402
from app.api import legacy as legacy_api  # noqa: E402
from app.api.exception_handlers import (  # noqa: E402
    handle_domain_error,
    handle_unhandled_exception,
    register_exception_handlers,
)
from app.auth.oidc import get_authenticator, oidc_enabled  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import check_database_connection  # noqa: E402
from app.core.idempotency import IdempotencyService, set_idempotency_service  # noqa: E402
from app.core.logger import configure_logging, get_logger  # noqa: E402
from app.core.middleware import RequestLoggingMiddleware  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.middleware.idempotency_middleware import IdempotencyMiddleware  # noqa: E402

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis_client: redis.Redis | None = None
    idempotency_service: IdempotencyService | None = None
    rate_limiter: RateLimiter | None = None

    if settings.is_production and not oidc_enabled():
        raise RuntimeError("OIDC_ENABLED must be true when ENV=production")

    await check_database_connection()
    logger.info("database_connected")

    if oidc_enabled():
        get_authenticator()
        logger.info("oidc_enabled", audience=settings.oidc_audience)
    else:
        logger.warning("oidc_disabled")

    if settings.idempotency_enabled or settings.rate_limit_enabled:
        try:
            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
        except Exception as exc:
            logger.critical("redis_startup_failed", error=str(exc), exc_info=True)
            raise

    if settings.idempotency_enabled and redis_client is not None:
        idempotency_service = IdempotencyService(
            redis_client,
            ttl_processing=settings.redis_ttl_processing,
            ttl_completed=settings.redis_ttl_completed,
        )
        logger.info(
            "idempotency_enabled",
            redis_url=settings.redis_url.split("@")[-1],
        )

    if settings.rate_limit_enabled and redis_client is not None:
        rate_limiter = RateLimiter(
            redis_client,
            limit=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
        logger.info("rate_limit_enabled", limit=settings.rate_limit_requests)

    app.state.redis_client = redis_client
    app.state.idempotency_service = idempotency_service
    app.state.rate_limiter = rate_limiter
    set_idempotency_service(idempotency_service)

    logger.info("application_startup", status="ready", env=settings.env)
    try:
        yield
    finally:
        if redis_client is not None:
            await redis_client.aclose()
        set_idempotency_service(None)
        logger.info("application_shutdown", status="stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="E-Bank API (DEMO)",
        description=(
            "DEMO ONLY — virtual portfolio bank. "
            "No real money. Welcome grant of play funds on bootstrap. "
            "Due diligence onboarding is optional and skippable."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    application.add_middleware(IdempotencyMiddleware)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Idempotency-Key",
            "X-Kalke-User-Sub",
            "X-Kalke-User-Email",
            "X-Kalke-Forward-Secret",
            "X-Request-ID",
        ],
    )

    application.include_router(health_api.router)
    application.include_router(demo_api.router)
    if settings.legacy_challenge_routes:
        application.include_router(legacy_api.router)

    register_exception_handlers(application)
    return application


app = create_app()

__all__ = ["app", "create_app", "handle_domain_error", "handle_unhandled_exception"]
