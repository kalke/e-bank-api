from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request

from app.auth.oidc import AuthError, Principal, get_authenticator


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def _admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "henriquekalke@icloud.com")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin_principal(principal: Principal) -> bool:
    if "admin" not in principal.permissions:
        return False
    email = (principal.email or "").strip().lower()
    return bool(email) and email in _admin_emails()


async def require_principal(request: Request) -> Principal:
    """Require a valid JWT or PAT. OIDC off is allowed only outside production (tests)."""
    authenticator = get_authenticator()
    if authenticator is None:
        # Production refuses to start with OIDC_ENABLED=false (see app.main lifespan).
        return Principal(
            subject="local-test",
            client="test",
            email="henriquekalke@icloud.com",
            permissions=["admin"],
        )
    try:
        return authenticator.authenticate(_bearer_token(request))
    except AuthError as exc:
        raise HTTPException(status_code=401, detail={"message": str(exc)}) from exc


async def require_admin(
    principal: Principal = Depends(require_principal),
) -> Principal:
    if not is_admin_principal(principal):
        raise HTTPException(
            status_code=403,
            detail={"message": "admin required"},
        )
    return principal


# Back-compat alias used by older imports/tests.
require_bank_write = require_admin
