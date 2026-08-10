from fastapi.testclient import TestClient

# Valid CPF (check digits).
VALID_CPF = "39053344705"


def _open_account(client: TestClient) -> dict:
    client.post("/v1/onboarding/start")
    skip = client.post("/v1/onboarding/skip")
    assert skip.status_code == 200
    return skip.json()


def test_demo_meta(client: TestClient) -> None:
    response = client.get("/v1/demo/meta")
    assert response.status_code == 200
    data = response.json()
    assert data["demo"] is True
    assert data["welcome_amount"] == "10000.00"
    assert "double_entry_ledger" in data["features"]


def test_bootstrap_requires_onboarding(client: TestClient) -> None:
    response = client.post("/v1/demo/bootstrap")
    assert response.status_code == 400


def test_skip_opens_account_with_number(client: TestClient) -> None:
    from uuid import UUID

    body = _open_account(client)
    assert body["onboarding_status"] == "skipped"
    assert body["balance"] == "10000.00"
    assert body["display_number"]
    assert body["account_number"] >= 100000
    assert 0 <= body["digit"] <= 9
    UUID(body["id"])  # public account id is UUID v4

    again = client.post("/v1/onboarding/skip")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    assert again.json()["balance"] == "10000.00"

    account = client.get("/v1/me/account")
    assert account.status_code == 200
    assert account.json()["display_number"] == body["display_number"]

    txns = client.get("/v1/me/transactions")
    assert txns.status_code == 200
    page = txns.json()
    assert page["transactions"]
    UUID(page["transactions"][0]["id"])
    if page["next_cursor"] is not None:
        UUID(page["next_cursor"])


def test_skip_then_complete_keeps_same_user_account(client: TestClient) -> None:
    """Re-running KYC after skip must upgrade the same subject-owned account."""
    skipped = _open_account(client)
    account_id = skipped["id"]

    # Wizard restart sets in_progress (same as the playground confirm flow).
    client.post("/v1/onboarding/start")
    assert client.get("/v1/me/account").status_code == 400

    complete = client.post(
        "/v1/onboarding/complete",
        json={
            "full_name": "Maria Silva",
            "birth_date": "1990-05-20",
            "document_number": VALID_CPF,
            "cep": "01310100",
            "street": "Av Paulista",
            "number": "1000",
            "email": "maria@example.com",
            "phone": "11987654321",
            "terms_accepted": True,
        },
    )
    assert complete.status_code == 200, complete.json()
    body = complete.json()
    assert body["id"] == account_id
    assert body["onboarding_status"] == "completed"
    assert body["holder_name"] == "Maria Silva"
    assert body["display_number"]

    me = client.get("/v1/me/account")
    assert me.status_code == 200
    assert me.json()["id"] == account_id
    assert me.json()["onboarding_status"] == "completed"


def test_onboarding_complete_full(client: TestClient) -> None:
    client.post("/v1/onboarding/start")
    complete = client.post(
        "/v1/onboarding/complete",
        json={
            "full_name": "Maria Silva",
            "birth_date": "1990-05-20",
            "document_number": VALID_CPF,
            "cep": "01310100",
            "street": "Av Paulista",
            "number": "1000",
            "complement": "cj 10",
            "neighborhood": "Bela Vista",
            "city": "Sao Paulo",
            "state": "SP",
            "email": "maria@example.com",
            "phone": "11987654321",
            "terms_accepted": True,
            "accepted_at": "2026-08-10T12:00:00Z",
        },
    )
    assert complete.status_code == 200
    body = complete.json()
    assert body["onboarding_status"] == "completed"
    assert body["holder_name"] == "Maria Silva"
    assert body["balance"] == "10000.00"


def test_onboarding_rejects_underage(client: TestClient) -> None:
    client.post("/v1/onboarding/start")
    response = client.post(
        "/v1/onboarding/complete",
        json={
            "full_name": "Kid",
            "birth_date": "2015-01-01",
            "document_number": VALID_CPF,
            "cep": "01310100",
            "street": "Rua A",
            "number": "1",
            "email": "kid@example.com",
            "phone": "11987654321",
            "terms_accepted": True,
        },
    )
    assert response.status_code == 400


def test_transfer_resolve_and_ledger(client: TestClient) -> None:
    a = _open_account(client)
    dest = client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-demo-1", "amount": 1},
    )
    assert dest.status_code == 201

    transfer = client.post(
        "/v1/me/transfer",
        headers={"Idempotency-Key": "xfer-test-1"},
        json={
            "destination_account_id": "dest-demo-1",
            "amount": "25.50",
            "memo": "demo payment",
        },
    )
    assert transfer.status_code == 200, transfer.json()
    assert transfer.json()["origin"]["balance"] == "9974.50"

    replay = client.post(
        "/v1/me/transfer",
        headers={"Idempotency-Key": "xfer-test-1"},
        json={
            "destination_account_id": "dest-demo-1",
            "amount": "25.50",
            "memo": "demo payment",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["origin"]["balance"] == "9974.50"

    me = client.get("/v1/me/account")
    assert me.json()["id"] == a["id"]
    assert me.json()["balance"] == "9974.50"


def test_transfer_limit(client: TestClient) -> None:
    _open_account(client)
    client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-demo-2", "amount": 1},
    )
    response = client.post(
        "/v1/me/transfer",
        headers={"Idempotency-Key": "xfer-limit"},
        json={"destination_account_id": "dest-demo-2", "amount": "10000.01"},
    )
    assert response.status_code == 400


def test_withdraw(client: TestClient) -> None:
    _open_account(client)
    response = client.post(
        "/v1/me/withdraw",
        headers={"Idempotency-Key": "wd-1"},
        json={"amount": "100.00"},
    )
    assert response.status_code == 200
    assert response.json()["balance"] == "9900.00"


def test_accounts_list(client: TestClient) -> None:
    opened = _open_account(client)
    listed = client.get("/v1/me/accounts")
    assert listed.status_code == 200
    rows = listed.json()["accounts"]
    assert len(rows) == 1
    assert rows[0]["display_number"] == opened["display_number"]


def test_resolve_by_document(client: TestClient) -> None:
    client.post("/v1/onboarding/start")
    client.post(
        "/v1/onboarding/complete",
        json={
            "full_name": "Maria Silva",
            "birth_date": "1990-05-20",
            "document_number": VALID_CPF,
            "cep": "01310100",
            "street": "Av Paulista",
            "number": "1000",
            "city": "Sao Paulo",
            "state": "SP",
            "email": "maria@example.com",
            "phone": "11987654321",
            "terms_accepted": True,
        },
    )
    resolved = client.post(
        "/v1/me/transfers/resolve",
        json={"document": VALID_CPF},
    )
    assert resolved.status_code == 200
    assert resolved.json()["holder_name"] == "Maria Silva"
    assert resolved.json()["document_masked"].endswith("05")


def test_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
