from app.auth.oidc import _permissions_from_claims


def test_permissions_fail_closed_when_empty() -> None:
    assert _permissions_from_claims({}) == []


def test_permissions_from_claim_list() -> None:
    assert _permissions_from_claims({"permissions": ["bank:write"]}) == ["bank:write"]


def test_permissions_from_scope() -> None:
    assert _permissions_from_claims({"scope": "bank:write openid"}) == [
        "bank:write",
        "openid",
    ]
