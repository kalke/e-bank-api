from decimal import Decimal, InvalidOperation

from app.errors import InvalidAmount


class Money:
    """Immutable monetary amount with two decimal places."""

    __slots__ = ("_amount",)

    def __init__(self, value: Decimal | str | int | float) -> None:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidAmount(str(value)) from exc
        if amount != amount.quantize(Decimal("0.01")):
            amount = amount.quantize(Decimal("0.01"))
        self._amount = amount

    @property
    def amount(self) -> Decimal:
        return self._amount

    def as_str(self) -> str:
        return f"{self._amount:.2f}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Money):
            return self._amount == other._amount
        return NotImplemented

    def __repr__(self) -> str:
        return f"Money({self.as_str()!r})"


def parse_positive_money(value: str | Decimal | int | float) -> Money:
    money = Money(value)
    if money.amount <= 0:
        raise InvalidAmount(str(value))
    return money
