import pytest
from fastapi import HTTPException

from app.auth.deps import require_authenticated_bank_write
from app.auth.oidc import Principal, _permissions_from_claims


def test_permissions_fail_closed_when_empty() -> None:
    assert _permissions_from_claims({}) == []


def test_permissions_from_claim_list() -> None:
    assert _permissions_from_claims({"permissions": ["bank:write"]}) == ["bank:write"]


def test_permissions_from_scope() -> None:
    assert _permissions_from_claims({"scope": "bank:write openid"}) == [
        "bank:write",
        "openid",
    ]


@pytest.mark.asyncio
async def test_demo_routes_reject_raw_m2m() -> None:
    principal = Principal(
        subject="service-account-ebank-m2m",
        permissions=["bank:write"],
        is_m2m=True,
    )
    with pytest.raises(HTTPException) as exc:
        await require_authenticated_bank_write(principal)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_demo_routes_accept_forwarded_end_user() -> None:
    principal = Principal(
        subject="user-sub",
        email="user@example.com",
        permissions=["bank:write"],
        is_m2m=False,
    )
    got = await require_authenticated_bank_write(principal)
    assert got.subject == "user-sub"
