from dataclasses import dataclass

from app.core.logger import get_logger
from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.store import InMemoryStore

logger = get_logger(__name__)


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
        logger.info("accounts_reset")

    def get_balance(self, account_id: str) -> int:
        balance = self._store.get_balance(account_id)
        if balance is None:
            logger.warning("account_not_found", account_id=account_id)
            raise AccountNotFound(account_id)
        logger.debug("balance_retrieved", account_id=account_id, balance=balance)
        return balance

    def deposit(self, destination: str, amount: int) -> Account:
        self._validate_amount(amount)
        current = self._store.get_balance(destination) or 0
        new_balance = current + amount
        self._store.set_balance(destination, new_balance)
        logger.info(
            "deposit_completed",
            destination=destination,
            amount=amount,
            previous_balance=current,
            new_balance=new_balance,
        )
        return Account(id=destination, balance=new_balance)

    def withdraw(self, origin: str, amount: int) -> Account:
        self._validate_amount(amount)
        current = self._store.get_balance(origin)
        if current is None:
            logger.warning("account_not_found", account_id=origin)
            raise AccountNotFound(origin)
        self._validate_limit(origin, current, amount)
        new_balance = current - amount
        self._store.set_balance(origin, new_balance)
        logger.info(
            "withdraw_completed",
            origin=origin,
            amount=amount,
            previous_balance=current,
            new_balance=new_balance,
        )
        return Account(id=origin, balance=new_balance)

    def transfer(
        self, origin: str, destination: str, amount: int
    ) -> tuple[Account, Account]:
        self._validate_amount(amount)
        origin_balance = self._store.get_balance(origin)
        if origin_balance is None:
            logger.warning("account_not_found", account_id=origin)
            raise AccountNotFound(origin)
        self._validate_limit(origin, origin_balance, amount)

        dest_balance = self._store.get_balance(destination) or 0
        new_origin_balance = origin_balance - amount
        new_dest_balance = dest_balance + amount

        self._store.set_balance(origin, new_origin_balance)
        self._store.set_balance(destination, new_dest_balance)

        logger.info(
            "transfer_completed",
            origin=origin,
            destination=destination,
            amount=amount,
            origin_previous_balance=origin_balance,
            origin_new_balance=new_origin_balance,
            destination_previous_balance=dest_balance,
            destination_new_balance=new_dest_balance,
        )

        return (
            Account(id=origin, balance=new_origin_balance),
            Account(id=destination, balance=new_dest_balance),
        )

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if amount <= 0:
            logger.warning("invalid_amount", amount=amount)
            raise InvalidAmount(amount)

    def _validate_limit(self, origin: str, current: int, amount: int) -> None:
        if current - amount < self.OVERDRAFT_LIMIT:
            logger.warning(
                "insufficient_funds",
                account_id=origin,
                current_balance=current,
                amount=amount,
                overdraft_limit=self.OVERDRAFT_LIMIT,
            )
            raise InsufficientFunds(origin)
