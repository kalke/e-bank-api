import pytest
from pydantic import ValidationError

from app.schemas import EventIn


def test_deposit_event_valid() -> None:
    event = EventIn(type="deposit", destination="100", amount=10)
    assert event.destination == "100"
    assert event.amount == 10


def test_withdraw_requires_origin() -> None:
    with pytest.raises(ValidationError):
        EventIn(type="withdraw", amount=10)


def test_transfer_requires_origin_and_destination() -> None:
    with pytest.raises(ValidationError):
        EventIn(type="transfer", origin="100", amount=10)
    with pytest.raises(ValidationError):
        EventIn(type="transfer", destination="300", amount=10)


def test_amount_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        EventIn(type="deposit", destination="100", amount=0)
    with pytest.raises(ValidationError):
        EventIn(type="deposit", destination="100", amount=-5)
