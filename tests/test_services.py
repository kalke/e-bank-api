import pytest

from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.services import AccountService


async def test_deposit_creates_and_increases_balance(service: AccountService) -> None:
    first = await service.deposit("100", 10)
    assert first.id == "100"
    assert first.balance == 10

    second = await service.deposit("100", 10)
    assert second.balance == 20


async def test_get_balance_existing_account(service: AccountService) -> None:
    await service.deposit("100", 10)
    assert await service.get_balance("100") == 10


async def test_get_balance_non_existing_account(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        await service.get_balance("1234")


async def test_withdraw_reduces_balance(service: AccountService) -> None:
    await service.deposit("100", 20)
    result = await service.withdraw("100", 5)
    assert result.balance == 15
    assert await service.get_balance("100") == 15


async def test_withdraw_non_existing_account(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        await service.withdraw("200", 10)


async def test_withdraw_insufficient_funds_does_not_change_balance(
    service: AccountService,
) -> None:
    await service.deposit("100", 5)
    with pytest.raises(InsufficientFunds):
        await service.withdraw("100", 1006)
    assert await service.get_balance("100") == 5


async def test_transfer_updates_origin_and_destination(service: AccountService) -> None:
    await service.deposit("100", 15)
    origin, destination = await service.transfer("100", "300", 15)
    assert origin.balance == 0
    assert destination.id == "300"
    assert destination.balance == 15
    assert await service.get_balance("100") == 0
    assert await service.get_balance("300") == 15


async def test_transfer_non_existing_origin(service: AccountService) -> None:
    with pytest.raises(AccountNotFound):
        await service.transfer("200", "300", 15)


async def test_transfer_insufficient_funds_does_not_change_state(
    service: AccountService,
) -> None:
    await service.deposit("100", 5)
    with pytest.raises(InsufficientFunds):
        await service.transfer("100", "300", 1006)
    assert await service.get_balance("100") == 5
    with pytest.raises(AccountNotFound):
        await service.get_balance("300")


async def test_reset_clears_state(service: AccountService) -> None:
    await service.deposit("100", 10)
    await service.reset()
    with pytest.raises(AccountNotFound):
        await service.get_balance("100")


async def test_invalid_amount(service: AccountService) -> None:
    with pytest.raises(InvalidAmount):
        await service.deposit("100", 0)
    with pytest.raises(InvalidAmount):
        await service.withdraw("100", -1)
    with pytest.raises(InvalidAmount):
        await service.transfer("100", "200", 0)


async def test_withdraw_entire_balance(service: AccountService) -> None:
    await service.deposit("100", 10)
    result = await service.withdraw("100", 10)
    assert result.balance == 0
    assert await service.get_balance("100") == 0


async def test_transfer_adds_to_existing_destination_balance(
    service: AccountService,
) -> None:
    await service.deposit("100", 20)
    await service.deposit("300", 5)
    origin, destination = await service.transfer("100", "300", 10)
    assert origin.balance == 10
    assert destination.balance == 15


async def test_insufficient_funds_carries_account_id(service: AccountService) -> None:
    await service.deposit("100", 3)
    with pytest.raises(InsufficientFunds) as exc_info:
        await service.withdraw("100", 1004)
    assert exc_info.value.account_id == "100"


async def test_transfer_allows_negative_balance_up_to_overdraft_limit(
    service: AccountService,
) -> None:
    await service.deposit("100", 50)
    origin, destination = await service.transfer("100", "300", 1050)
    assert origin.balance == -1000
    assert destination.balance == 1050


async def test_withdraw_allows_negative_balance_up_to_overdraft_limit(
    service: AccountService,
) -> None:
    await service.deposit("100", 100)
    result = await service.withdraw("100", 1100)
    assert result.balance == -1000
