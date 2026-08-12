from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth.oidc import (
    HEADER_FORWARD_SECRET,
    HEADER_USER_EMAIL,
    HEADER_USER_SUB,
    AuthError,
    Principal,
    get_authenticator,
    oidc_enabled,
    resolve_effective_principal,
)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def _forward_headers(request: Request) -> dict[str, str]:
    return {
        HEADER_FORWARD_SECRET: request.headers.get(HEADER_FORWARD_SECRET) or "",
        HEADER_USER_SUB: request.headers.get(HEADER_USER_SUB) or "",
        HEADER_USER_EMAIL: request.headers.get(HEADER_USER_EMAIL) or "",
    }


async def require_principal(request: Request) -> Principal | None:
    if not oidc_enabled() or get_authenticator() is None:
        return None
    try:
        principal = resolve_effective_principal(
            _bearer_token(request),
            _forward_headers(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail={"message": str(exc)}) from exc
    request.state.user_id = principal.subject
    request.state.principal = principal
    return principal


async def require_bank_write(
    principal: Principal | None = Depends(require_principal),
) -> Principal | None:
    if principal is None:
        return None
    if not principal.has_permission("bank:write"):
        raise HTTPException(
            status_code=403,
            detail={"message": "missing permission bank:write"},
        )
    return principal


async def require_authenticated_bank_write(
    principal: Principal | None = Depends(require_bank_write),
) -> Principal:
    """Require a real end-user principal (OIDC on in production)."""
    if principal is None:
        # Dev/test without OIDC: synthetic principal for local demo routes
        if not oidc_enabled():
            return Principal(
                subject="local-dev",
                email="dev@localhost",
                permissions=["bank:write"],
            )
        raise HTTPException(status_code=401, detail={"message": "unauthorized"})
    if principal.is_m2m:
        raise HTTPException(
            status_code=403,
            detail={"message": "end-user session required"},
        )
    return principal
