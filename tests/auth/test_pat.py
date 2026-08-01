from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.auth.oidc import AuthError, OIDCAuthenticator, Principal


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_pat_requires_introspect_config() -> None:
    auth = OIDCAuthenticator.__new__(OIDCAuthenticator)
    auth.introspect_url = ""
    auth.introspect_secret = ""
    with pytest.raises(AuthError):
        auth._authenticate_pat("kalke_testtokenvalue000")


def test_pat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = OIDCAuthenticator.__new__(OIDCAuthenticator)
    auth.introspect_url = "https://auth.example/v1/introspect"
    auth.introspect_secret = "secret"

    def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:
        assert req.get_full_url() == "https://auth.example/v1/introspect"  # type: ignore[attr-defined]
        assert req.get_header("X-kalke-introspect-key") == "secret"  # type: ignore[attr-defined]
        return _FakeResp(
            {
                "active": True,
                "sub": "user-1",
                "email": "henrique@example.com",
                "permissions": ["bank:write"],
            }
        )

    monkeypatch.setattr("app.auth.oidc.urlopen", fake_urlopen)
    principal = auth._authenticate_pat("kalke_abcdefghijklmnopqrstuv")
    assert isinstance(principal, Principal)
    assert principal.subject == "user-1"
    assert principal.client == "kalke-pat"
    assert principal.has_permission("bank:write")


def test_pat_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = OIDCAuthenticator.__new__(OIDCAuthenticator)
    auth.introspect_url = "https://auth.example/v1/introspect"
    auth.introspect_secret = "secret"
    monkeypatch.setattr(
        "app.auth.oidc.urlopen",
        lambda *a, **k: _FakeResp({"active": False}),
    )
    with pytest.raises(AuthError):
        auth._authenticate_pat("kalke_abcdefghijklmnopqrstuv")


def test_pat_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = OIDCAuthenticator.__new__(OIDCAuthenticator)
    auth.introspect_url = "https://auth.example/v1/introspect"
    auth.introspect_secret = "secret"

    def boom(*_a: object, **_k: object) -> BytesIO:
        raise HTTPError(
            "https://auth.example/v1/introspect",
            401,
            "unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

    monkeypatch.setattr("app.auth.oidc.urlopen", boom)
    with pytest.raises(AuthError):
        auth._authenticate_pat("kalke_abcdefghijklmnopqrstuv")
