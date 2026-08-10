from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()
    try:
        await check_database_connection()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "down"},
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "ready",
            "database": "up",
            "idempotency": settings.idempotency_enabled,
            "demo": True,
        },
    )
