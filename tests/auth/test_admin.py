from __future__ import annotations

import pytest

from app.auth.deps import is_admin_principal
from app.auth.oidc import Principal


def test_admin_requires_role_and_allowlisted_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_EMAILS", "henriquekalke@icloud.com")
    assert is_admin_principal(
        Principal(
            subject="1",
            email="henriquekalke@icloud.com",
            permissions=["admin"],
        )
    )
    assert not is_admin_principal(
        Principal(
            subject="1",
            email="other@example.com",
            permissions=["admin"],
        )
    )
    assert not is_admin_principal(
        Principal(
            subject="1",
            email="henriquekalke@icloud.com",
            permissions=["bank:write"],
        )
    )
    assert not is_admin_principal(
        Principal(subject="1", email="", permissions=["admin"])
    )
