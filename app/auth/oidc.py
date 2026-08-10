from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import get_settings


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
    is_m2m: bool = False

    def has_permission(self, want: str) -> bool:
        if "admin" in self.permissions:
            return True
        if want in self.permissions:
            return True
        return want == "bank:write" and "bank:demo" in self.permissions


HEADER_USER_SUB = "X-Kalke-User-Sub"
HEADER_USER_EMAIL = "X-Kalke-User-Email"
HEADER_FORWARD_SECRET = "X-Kalke-Forward-Secret"


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
        client = str(claims.get("azp") or claims.get("client_id") or "").strip()
        is_m2m = _is_m2m_claims(claims)
        return Principal(
            subject=sub,
            client=client,
            email=str(claims.get("email") or "").strip(),
            permissions=permissions,
            is_m2m=is_m2m,
        )


_authenticator: OIDCAuthenticator | None = None
_lock = threading.Lock()


def oidc_enabled() -> bool:
    return get_settings().oidc_enabled


def get_authenticator() -> OIDCAuthenticator | None:
    global _authenticator
    if not oidc_enabled():
        return None
    if _authenticator is not None:
        return _authenticator
    with _lock:
        if _authenticator is not None:
            return _authenticator
        settings = get_settings()
        issuer = settings.oidc_issuer.strip()
        audience = settings.oidc_audience.strip()
        if not issuer or not audience:
            raise RuntimeError(
                "OIDC_ISSUER and OIDC_AUDIENCE are required when OIDC_ENABLED=true"
            )
        discovery = settings.oidc_discovery_url.strip() or None
        _authenticator = OIDCAuthenticator(issuer, audience, discovery)
        return _authenticator


def reset_authenticator() -> None:
    global _authenticator
    with _lock:
        _authenticator = None


def resolve_effective_principal(
    bearer_token: str,
    headers: dict[str, str],
) -> Principal:
    """Authenticate JWT and optionally rewrite subject from trusted BFF forward."""
    authenticator = get_authenticator()
    if authenticator is None:
        raise AuthError("oidc disabled")
    principal = authenticator.authenticate(bearer_token)
    if not principal.is_m2m:
        return principal

    settings = get_settings()
    expected = settings.m2m_user_forward_secret.strip()
    provided = (headers.get(HEADER_FORWARD_SECRET) or "").strip()
    if not expected or provided != expected:
        # M2M without trusted forward stays as service principal
        return principal

    forwarded_sub = (headers.get(HEADER_USER_SUB) or "").strip()
    if not forwarded_sub:
        raise AuthError("missing forwarded user")
    forwarded_email = (headers.get(HEADER_USER_EMAIL) or "").strip()
    return Principal(
        subject=forwarded_sub,
        client=principal.client,
        email=forwarded_email or principal.email,
        permissions=principal.permissions or ["bank:write"],
        is_m2m=False,
    )


def _discover(base: str) -> tuple[str, str]:
    url = f"{base}/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        doc: dict[str, Any] = resp.json()
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
    """Fail closed: never invent write access when claims are empty."""
    permissions = claims.get("permissions")
    if isinstance(permissions, list) and permissions:
        return [str(p) for p in permissions]
    scope = claims.get("scope")
    if isinstance(scope, str) and scope.strip():
        return scope.split()
    return []


def _is_m2m_claims(claims: dict[str, Any]) -> bool:
    if claims.get("email"):
        return False
    # client_credentials tokens typically have azp/client_id and grant_type
    grant = str(claims.get("grant_type") or "").lower()
    if grant == "client_credentials":
        return True
    preferred = str(claims.get("preferred_username") or "")
    if preferred.endswith("-service") or preferred.endswith("-m2m"):
        return True
    # Heuristic: service accounts often have sub == client id style without @
    azp = str(claims.get("azp") or claims.get("client_id") or "")
    sub = str(claims.get("sub") or "")
    if azp and sub and ("service-account" in preferred or azp in sub):
        return True
    return "service-account-" in preferred
