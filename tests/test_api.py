import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    client.post("/reset")


def test_full_flow_from_spec() -> None:
    response = client.get("/balance", params={"account_id": "1234"})
    assert response.status_code == 404
    assert response.json() == {"message": "Account 1234 not found"}

    response = client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 10},
    )
    assert response.status_code == 201
    assert response.json() == {"destination": {"id": "100", "balance": 10}}

    response = client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 10},
    )
    assert response.status_code == 201
    assert response.json() == {"destination": {"id": "100", "balance": 20}}

    response = client.get("/balance", params={"account_id": "100"})
    assert response.status_code == 200
    assert response.text == "20"

    response = client.post(
        "/event",
        json={"type": "withdraw", "origin": "200", "amount": 10},
    )
    assert response.status_code == 404
    assert response.json() == {"message": "Account 200 not found"}

    response = client.post(
        "/event",
        json={"type": "withdraw", "origin": "100", "amount": 5},
    )
    assert response.status_code == 201
    assert response.json() == {"origin": {"id": "100", "balance": 15}}

    response = client.post(
        "/event",
        json={
            "type": "transfer",
            "origin": "100",
            "amount": 15,
            "destination": "300",
        },
    )
    assert response.status_code == 201
    assert response.json() == {
        "origin": {"id": "100", "balance": 0},
        "destination": {"id": "300", "balance": 15},
    }

    response = client.post(
        "/event",
        json={
            "type": "transfer",
            "origin": "200",
            "amount": 15,
            "destination": "300",
        },
    )
    assert response.status_code == 404
    assert response.json() == {"message": "Account 200 not found"}


def test_insufficient_funds_withdraw() -> None:
    client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 5},
    )

    response = client.post(
        "/event",
        json={"type": "withdraw", "origin": "100", "amount": 10},
    )
    assert response.status_code == 400
    assert response.json() == {"message": "Account 100 has insufficient funds"}

    balance = client.get("/balance", params={"account_id": "100"})
    assert balance.status_code == 200
    assert balance.text == "5"


def test_insufficient_funds_transfer() -> None:
    client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 5},
    )

    response = client.post(
        "/event",
        json={
            "type": "transfer",
            "origin": "100",
            "amount": 15,
            "destination": "300",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"message": "Account 100 has insufficient funds"}

    origin = client.get("/balance", params={"account_id": "100"})
    assert origin.text == "5"

    dest = client.get("/balance", params={"account_id": "300"})
    assert dest.status_code == 404


def test_reset_clears_state() -> None:
    client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 10},
    )
    client.post("/reset")
    response = client.get("/balance", params={"account_id": "100"})
    assert response.status_code == 404
    assert response.json() == {"message": "Account 100 not found"}


def test_reset_returns_200_ok() -> None:
    response = client.post("/reset")
    assert response.status_code == 200
    assert response.text == "OK"


def test_balance_requires_account_id() -> None:
    response = client.get("/balance")
    assert response.status_code == 422


def test_deposit_missing_destination_returns_422() -> None:
    response = client.post(
        "/event",
        json={"type": "deposit", "amount": 10},
    )
    assert response.status_code == 422


def test_withdraw_missing_origin_returns_422() -> None:
    response = client.post(
        "/event",
        json={"type": "withdraw", "amount": 10},
    )
    assert response.status_code == 422


def test_transfer_missing_fields_returns_422() -> None:
    response = client.post(
        "/event",
        json={"type": "transfer", "origin": "100", "amount": 10},
    )
    assert response.status_code == 422


def test_event_invalid_amount_returns_422() -> None:
    response = client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 0},
    )
    assert response.status_code == 422


def test_get_balance_after_deposit() -> None:
    client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 10},
    )
    response = client.get("/balance", params={"account_id": "100"})
    assert response.status_code == 200
    assert response.text == "10"


def test_transfer_creates_destination_account() -> None:
    client.post(
        "/event",
        json={"type": "deposit", "destination": "100", "amount": 20},
    )
    response = client.post(
        "/event",
        json={
            "type": "transfer",
            "origin": "100",
            "amount": 7,
            "destination": "300",
        },
    )
    assert response.status_code == 201
    assert response.json() == {
        "origin": {"id": "100", "balance": 13},
        "destination": {"id": "300", "balance": 7},
    }
    assert client.get("/balance", params={"account_id": "300"}).text == "7"
