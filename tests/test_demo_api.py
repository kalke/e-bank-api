from fastapi.testclient import TestClient


def test_demo_meta(client: TestClient) -> None:
    response = client.get("/v1/demo/meta")
    assert response.status_code == 200
    data = response.json()
    assert data["demo"] is True
    assert data["welcome_amount"] == "10000.00"
    assert data["currency"] == "USD"
    assert "DEMO ONLY" in data["disclaimer"]


def test_bootstrap_credits_once(client: TestClient) -> None:
    first = client.post("/v1/demo/bootstrap")
    assert first.status_code == 200
    body = first.json()
    assert body["balance"] == "10000.00"
    assert body["demo_credited"] is True
    assert body["demo"] is True
    account_id = body["id"]

    second = client.post("/v1/demo/bootstrap")
    assert second.status_code == 200
    assert second.json()["balance"] == "10000.00"
    assert second.json()["id"] == account_id

    account = client.get("/v1/me/account")
    assert account.status_code == 200
    assert account.json()["balance"] == "10000.00"


def test_onboarding_skip_then_bank(client: TestClient) -> None:
    start = client.post("/v1/onboarding/start")
    assert start.status_code == 200
    assert start.json()["skippable"] is True

    skip = client.post("/v1/onboarding/skip")
    assert skip.status_code == 200
    assert skip.json()["onboarding_status"] == "skipped"

    boot = client.post("/v1/demo/bootstrap")
    assert boot.status_code == 200
    assert boot.json()["balance"] == "10000.00"
    assert boot.json()["onboarding_status"] == "skipped"


def test_onboarding_document_and_complete(client: TestClient) -> None:
    client.post("/v1/onboarding/start")
    client.post(
        "/v1/onboarding/consent",
        json={"policy_version": "demo-bank-tos-v1"},
    )
    docs = client.post(
        "/v1/onboarding/documents",
        json={
            "doc_type": "identity_document",
            "pde_extraction_id": "ext_test_1",
            "summary": {"name": "Demo User", "cpf": "12345678901"},
        },
    )
    assert docs.status_code == 200
    assert len(docs.json()["documents"]) == 1
    # cpf should be redacted in stored summary path — response lists metadata only
    complete = client.post("/v1/onboarding/complete")
    assert complete.status_code == 200
    assert complete.json()["onboarding_status"] == "completed"


def test_transfer_and_transactions(client: TestClient) -> None:
    a = client.post("/v1/demo/bootstrap").json()
    # Create destination via second synthetic user by direct service is hard;
    # use legacy deposit to create dest account then transfer to it.
    dest = client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-demo-1", "amount": 1},
    )
    assert dest.status_code == 201

    transfer = client.post(
        "/v1/me/transfer",
        json={
            "destination_account_id": "dest-demo-1",
            "amount": "25.50",
            "memo": "demo payment",
        },
    )
    assert transfer.status_code == 200
    assert transfer.json()["origin"]["balance"] == "9974.50"
    assert transfer.json()["destination"]["balance"] == "26.50"

    txs = client.get("/v1/me/transactions")
    assert txs.status_code == 200
    assert len(txs.json()["transactions"]) >= 2

    me = client.get("/v1/me/account")
    assert me.json()["id"] == a["id"]
    assert me.json()["balance"] == "9974.50"


def test_transfer_limit(client: TestClient) -> None:
    client.post("/v1/demo/bootstrap")
    client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-demo-2", "amount": 1},
    )
    response = client.post(
        "/v1/me/transfer",
        json={"destination_account_id": "dest-demo-2", "amount": "10000.01"},
    )
    assert response.status_code == 400


def test_withdraw(client: TestClient) -> None:
    client.post("/v1/demo/bootstrap")
    response = client.post("/v1/me/withdraw", json={"amount": "100.00"})
    assert response.status_code == 200
    assert response.json()["balance"] == "9900.00"


def test_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
