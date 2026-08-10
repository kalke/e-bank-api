from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

from app.errors import AccountNotFound, InsufficientFunds
from app.services import AccountService

OVERDRAFT_LIMIT = AccountService.OVERDRAFT_LIMIT


@pytest.fixture(autouse=True)
def reset_api_state(client: TestClient) -> None:
    client.post("/reset")


class TestOverdraftLimitService:
    async def test_withdraw_from_zero_balance_goes_negative(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", 0)

        result = await service.withdraw("100", 100)
        assert result.balance == -100

    async def test_transfer_from_zero_balance_goes_negative(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", 0)

        origin, destination = await service.transfer("100", "300", 250)
        assert origin.balance == -250
        assert destination.balance == 250

    async def test_withdraw_exactly_at_overdraft_limit(
        self,
        service: AccountService,
    ) -> None:
        await service.deposit("100", 200)

        result = await service.withdraw("100", 1200)
        assert result.balance == OVERDRAFT_LIMIT

    async def test_transfer_exactly_at_overdraft_limit(
        self,
        service: AccountService,
    ) -> None:
        await service.deposit("100", 200)

        origin, destination = await service.transfer("100", "300", 1200)
        assert origin.balance == OVERDRAFT_LIMIT
        assert destination.balance == 1200

    async def test_withdraw_one_over_overdraft_limit_is_rejected(
        self,
        service: AccountService,
    ) -> None:
        await service.deposit("100", 200)

        with pytest.raises(InsufficientFunds):
            await service.withdraw("100", 1201)

        assert await service.get_balance("100") == 200

    async def test_transfer_one_over_overdraft_limit_is_rejected(
        self,
        service: AccountService,
    ) -> None:
        await service.deposit("100", 200)

        with pytest.raises(InsufficientFunds):
            await service.transfer("100", "300", 1201)

        assert await service.get_balance("100") == 200
        with pytest.raises(AccountNotFound):
            await service.get_balance("300")

    async def test_withdraw_from_account_already_at_limit_is_rejected(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", OVERDRAFT_LIMIT)

        with pytest.raises(InsufficientFunds):
            await service.withdraw("100", 1)

        assert await service.get_balance("100") == OVERDRAFT_LIMIT

    async def test_transfer_from_account_already_at_limit_is_rejected(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", OVERDRAFT_LIMIT)

        with pytest.raises(InsufficientFunds):
            await service.transfer("100", "300", 1)

        assert await service.get_balance("100") == OVERDRAFT_LIMIT

    async def test_withdraw_from_negative_balance_up_to_limit(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", -700)

        result = await service.withdraw("100", 300)
        assert result.balance == OVERDRAFT_LIMIT

    async def test_transfer_from_negative_balance_up_to_limit(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", -700)

        origin, destination = await service.transfer("100", "300", 300)
        assert origin.balance == OVERDRAFT_LIMIT
        assert destination.balance == 300

    async def test_withdraw_from_negative_balance_one_over_limit_is_rejected(
        self,
        service: AccountService,
        set_balance: Callable[[str, int], Awaitable[None]],
    ) -> None:
        await set_balance("100", -700)

        with pytest.raises(InsufficientFunds):
            await service.withdraw("100", 301)

        assert await service.get_balance("100") == -700

    async def test_transfer_over_limit_does_not_change_destination(
        self,
        service: AccountService,
    ) -> None:
        await service.deposit("100", 10)
        await service.deposit("300", 50)

        with pytest.raises(InsufficientFunds):
            await service.transfer("100", "300", 1011)

        assert await service.get_balance("100") == 10
        assert await service.get_balance("300") == 50


class TestOverdraftLimitApi:
    def test_withdraw_from_zero_balance_goes_negative(self, client: TestClient) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 1},
        )
        client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 1},
        )

        response = client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 50},
        )
        assert response.status_code == 201
        assert response.json() == {"origin": {"id": "100", "balance": -50}}

    def test_transfer_from_zero_balance_goes_negative(self, client: TestClient) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 10},
        )
        client.post(
            "/event",
            json={
                "type": "transfer",
                "origin": "100",
                "amount": 10,
                "destination": "300",
            },
        )

        response = client.post(
            "/event",
            json={
                "type": "transfer",
                "origin": "100",
                "amount": 30,
                "destination": "300",
            },
        )
        assert response.status_code == 201
        assert response.json() == {
            "origin": {"id": "100", "balance": -30},
            "destination": {"id": "300", "balance": 40},
        }

    def test_withdraw_exactly_at_overdraft_limit(self, client: TestClient) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 200},
        )

        response = client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 1200},
        )
        assert response.status_code == 201
        assert response.json() == {"origin": {"id": "100", "balance": OVERDRAFT_LIMIT}}

    def test_transfer_exactly_at_overdraft_limit(self, client: TestClient) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 200},
        )

        response = client.post(
            "/event",
            json={
                "type": "transfer",
                "origin": "100",
                "amount": 1200,
                "destination": "300",
            },
        )
        assert response.status_code == 201
        assert response.json() == {
            "origin": {"id": "100", "balance": OVERDRAFT_LIMIT},
            "destination": {"id": "300", "balance": 1200},
        }

    def test_withdraw_one_over_overdraft_limit_returns_400(
        self,
        client: TestClient,
    ) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 200},
        )

        response = client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 1201},
        )
        assert response.status_code == 400
        assert response.json() == {"message": "Account 100 has insufficient funds"}
        assert client.get("/balance", params={"account_id": "100"}).text == "200"

    def test_transfer_one_over_overdraft_limit_returns_400(
        self,
        client: TestClient,
    ) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 200},
        )

        response = client.post(
            "/event",
            json={
                "type": "transfer",
                "origin": "100",
                "amount": 1201,
                "destination": "300",
            },
        )
        assert response.status_code == 400
        assert response.json() == {"message": "Account 100 has insufficient funds"}
        assert client.get("/balance", params={"account_id": "100"}).text == "200"
        assert client.get("/balance", params={"account_id": "300"}).status_code == 404

    def test_withdraw_from_account_at_limit_returns_400(
        self,
        client: TestClient,
    ) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 100},
        )
        client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 1100},
        )
        assert client.get("/balance", params={"account_id": "100"}).text == str(
            OVERDRAFT_LIMIT
        )

        response = client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 1},
        )
        assert response.status_code == 400
        assert response.json() == {"message": "Account 100 has insufficient funds"}

    def test_transfer_from_negative_balance_up_to_limit(
        self,
        client: TestClient,
    ) -> None:
        client.post(
            "/event",
            json={"type": "deposit", "destination": "100", "amount": 100},
        )
        client.post(
            "/event",
            json={"type": "withdraw", "origin": "100", "amount": 800},
        )
        assert client.get("/balance", params={"account_id": "100"}).text == "-700"

        response = client.post(
            "/event",
            json={
                "type": "transfer",
                "origin": "100",
                "amount": 300,
                "destination": "300",
            },
        )
        assert response.status_code == 201
        assert response.json() == {
            "origin": {"id": "100", "balance": OVERDRAFT_LIMIT},
            "destination": {"id": "300", "balance": 300},
        }
