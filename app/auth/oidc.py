from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    def __init__(self, message: str = "unauthorized") -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Principal:
    subject: str
    client: str = ""
    email: str = ""
    permissions: list[str] = field(default_factory=list)

    def has_permission(self, want: str) -> bool:
        return "admin" in self.permissions or want in self.permissions


class OIDCAuthenticator:
    def __init__(
        self,
        issuer: str,
        audience: str,
        discovery_url: str | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        discovery = (discovery_url or issuer).rstrip("/")
        jwks_uri, discovered_issuer = _discover(discovery)
        if not discovery_url and discovered_issuer:
            self.issuer = discovered_issuer.rstrip("/")
        if discovery_url:
            jwks_uri = _rewrite_origin(jwks_uri, discovery)
        self._jwks = PyJWKClient(jwks_uri, cache_keys=True)

    def authenticate(self, bearer_token: str) -> Principal:
        token = bearer_token.strip()
        if not token:
            raise AuthError()
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except Exception as exc:
            raise AuthError() from exc

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise AuthError()

        permissions = _permissions_from_claims(claims)
        return Principal(
            subject=sub,
            client=str(claims.get("azp") or "").strip(),
            email=str(claims.get("email") or "").strip(),
            permissions=permissions,
        )


_authenticator: OIDCAuthenticator | None = None
_lock = threading.Lock()


def oidc_enabled() -> bool:
    return os.getenv("OIDC_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def get_authenticator() -> OIDCAuthenticator | None:
    global _authenticator
    if not oidc_enabled():
        return None
    if _authenticator is not None:
        return _authenticator
    with _lock:
        if _authenticator is not None:
            return _authenticator
        issuer = os.getenv("OIDC_ISSUER", "").strip()
        audience = os.getenv("OIDC_AUDIENCE", "").strip()
        if not issuer or not audience:
            raise RuntimeError(
                "OIDC_ISSUER and OIDC_AUDIENCE are required when OIDC_ENABLED=true"
            )
        discovery = os.getenv("OIDC_DISCOVERY_URL", "").strip() or None
        _authenticator = OIDCAuthenticator(issuer, audience, discovery)
        return _authenticator


def reset_authenticator() -> None:
    global _authenticator
    with _lock:
        _authenticator = None


def _discover(base: str) -> tuple[str, str]:
    url = f"{base}/.well-known/openid-configuration"
    with urlopen(url, timeout=10) as resp:
        doc: dict[str, Any] = json.loads(resp.read().decode())
    jwks = doc.get("jwks_uri")
    if not jwks:
        raise RuntimeError("oidc discovery: missing jwks_uri")
    return str(jwks), str(doc.get("issuer") or "")


def _rewrite_origin(raw: str, origin_base: str) -> str:
    parsed = urlparse(raw)
    base = urlparse(origin_base)
    return urlunparse(
        (
            base.scheme,
            base.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _permissions_from_claims(claims: dict[str, Any]) -> list[str]:
    permissions = claims.get("permissions")
    if isinstance(permissions, list) and permissions:
        return [str(p) for p in permissions]
    scope = claims.get("scope")
    if isinstance(scope, str) and scope.strip():
        return scope.split()
    return ["bank:write"]
