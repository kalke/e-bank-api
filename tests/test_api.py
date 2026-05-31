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
    assert response.text == "0"

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
    assert response.text == "0"

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
    assert response.text == "0"


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
    assert response.text == "0"

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
    assert response.text == "0"

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
    assert response.text == "0"
