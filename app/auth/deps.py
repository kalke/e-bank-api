from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth.oidc import AuthError, Principal, get_authenticator


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


async def require_principal(request: Request) -> Principal | None:
    authenticator = get_authenticator()
    if authenticator is None:
        return None
    try:
        return authenticator.authenticate(_bearer_token(request))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail={"message": str(exc)}) from exc


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
