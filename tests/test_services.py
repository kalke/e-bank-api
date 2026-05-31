import pytest

from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.services import AccountService
from app.store import InMemoryStore


@pytest.fixture
def service() -> AccountService:
    return AccountService(InMemoryStore())


def test_deposit_creates_and_increases_balance(service: AccountService) -> None:
    first = service.deposit("100", 10)
    assert first.id == "100"
    assert first.balance == 10

    second = service.deposit("100", 10)
    assert second.balance == 20


def test_get_balance_existing_account(service: AccountService) -> None:
    service.deposit("100", 10)
    assert service.get_balance("100") == 10


def test_get_balance_non_existing_account(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        service.get_balance("1234")


def test_withdraw_reduces_balance(service: AccountService) -> None:
    service.deposit("100", 20)
    result = service.withdraw("100", 5)
    assert result.balance == 15
    assert service.get_balance("100") == 15


def test_withdraw_non_existing_account(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        service.withdraw("200", 10)


def test_withdraw_insufficient_funds_does_not_change_balance(
    service: AccountService,
) -> None:
    service.deposit("100", 5)
    with pytest.raises(InsufficientFunds):
        service.withdraw("100", 10)
    assert service.get_balance("100") == 5


def test_transfer_updates_origin_and_destination(service: AccountService) -> None:
    service.deposit("100", 15)
    origin, destination = service.transfer("100", "300", 15)
    assert origin.balance == 0
    assert destination.id == "300"
    assert destination.balance == 15
    assert service.get_balance("100") == 0
    assert service.get_balance("300") == 15


def test_transfer_non_existing_origin(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        service.transfer("200", "300", 15)


def test_transfer_insufficient_funds_does_not_change_state(
    service: AccountService,
) -> None:
    service.deposit("100", 5)
    with pytest.raises(InsufficientFunds):
        service.transfer("100", "300", 15)
    assert service.get_balance("100") == 5
    with pytest.raises(AccountNotFound):
        service.get_balance("300")


def test_reset_clears_state(service: AccountService) -> None:
    service.deposit("100", 10)
    service.reset()
    with pytest.raises(AccountNotFound):
        service.get_balance("100")


def test_invalid_amount(service: AccountService) -> None:
    with pytest.raises(InvalidAmount):
        service.deposit("100", 0)
    with pytest.raises(InvalidAmount):
        service.withdraw("100", -1)
    with pytest.raises(InvalidAmount):
        service.transfer("100", "200", 0)


def test_withdraw_entire_balance(service: AccountService) -> None:
    service.deposit("100", 10)
    result = service.withdraw("100", 10)
    assert result.balance == 0
    assert service.get_balance("100") == 0


def test_transfer_adds_to_existing_destination_balance(
    service: AccountService,
) -> None:
    service.deposit("100", 20)
    service.deposit("300", 5)
    origin, destination = service.transfer("100", "300", 10)
    assert origin.balance == 10
    assert destination.balance == 15


def test_insufficient_funds_carries_account_id(service: AccountService) -> None:
    service.deposit("100", 3)
    with pytest.raises(InsufficientFunds) as exc_info:
        service.withdraw("100", 10)
    assert exc_info.value.args[0] == "100"
