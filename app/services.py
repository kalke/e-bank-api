from dataclasses import dataclass

from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.store import InMemoryStore


@dataclass(frozen=True)
class Account:
    id: str
    balance: int


class AccountService:
    OVERDRAFT_LIMIT = -1000

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def reset(self) -> None:
        self._store.clear()

    def get_balance(self, account_id: str) -> int:
        balance = self._store.get_balance(account_id)
        if balance is None:
            raise AccountNotFound(account_id)
        return balance

    def deposit(self, destination: str, amount: int) -> Account:
        self._validate_amount(amount)
        current = self._store.get_balance(destination) or 0
        new_balance = current + amount
        self._store.set_balance(destination, new_balance)
        return Account(id=destination, balance=new_balance)

    def withdraw(self, origin: str, amount: int) -> Account:
        self._validate_amount(amount)
        current = self._store.get_balance(origin)
        if current is None:
            raise AccountNotFound(origin)
        self._validate_limit(origin, current, amount)
        new_balance = current - amount
        self._store.set_balance(origin, new_balance)
        return Account(id=origin, balance=new_balance)

    def transfer(
        self, origin: str, destination: str, amount: int
    ) -> tuple[Account, Account]:
        self._validate_amount(amount)
        origin_balance = self._store.get_balance(origin)
        if origin_balance is None:
            raise AccountNotFound(origin)
        self._validate_limit(origin, origin_balance, amount)

        dest_balance = self._store.get_balance(destination) or 0
        new_origin_balance = origin_balance - amount
        new_dest_balance = dest_balance + amount

        self._store.set_balance(origin, new_origin_balance)
        self._store.set_balance(destination, new_dest_balance)

        return (
            Account(id=origin, balance=new_origin_balance),
            Account(id=destination, balance=new_dest_balance),
        )

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if amount <= 0:
            raise InvalidAmount(amount)

    def _validate_limit(self, origin: str, current: int, amount: int) -> None:
        if current - amount < self.OVERDRAFT_LIMIT:
            raise InsufficientFunds(origin)
