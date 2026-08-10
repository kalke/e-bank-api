from dataclasses import dataclass
from decimal import Decimal

from app.core.logger import get_logger
from app.errors import AccountNotFound, InsufficientFunds, InvalidAmount
from app.repositories.account_repository import AccountRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class Account:
    id: str
    balance: int


class AccountService:
    """Legacy integer ledger service used by challenge-compatible routes/tests."""

    OVERDRAFT_LIMIT = -1000

    def __init__(self, repository: AccountRepository) -> None:
        self._repo = repository

    async def reset(self) -> None:
        await self._repo.delete_all()
        logger.info("accounts_reset")

    async def get_balance(self, account_id: str) -> int:
        account = await self._repo.get(account_id)
        if account is None:
            logger.warning("account_not_found", account_id=account_id)
            raise AccountNotFound(account_id)
        balance = _to_int_balance(account.balance)
        logger.debug("balance_retrieved", account_id=account_id, balance=balance)
        return balance

    async def deposit(self, destination: str, amount: int) -> Account:
        self._validate_amount(amount)
        amount_decimal = Decimal(amount)
        account = await self._repo.get_for_update(destination)
        if account is None:
            created = await self._repo.create(destination, amount_decimal)
            logger.info(
                "deposit_completed",
                destination=destination,
                amount=amount,
                previous_balance=0,
                new_balance=amount,
            )
            return Account(id=destination, balance=_to_int_balance(created.balance))

        previous_balance = _to_int_balance(account.balance)
        updated = await self._repo.record_transaction(
            destination,
            amount_decimal,
            "deposit",
        )
        new_balance_int = _to_int_balance(updated.balance)
        logger.info(
            "deposit_completed",
            destination=destination,
            amount=amount,
            previous_balance=previous_balance,
            new_balance=new_balance_int,
        )
        return Account(id=destination, balance=new_balance_int)

    async def withdraw(self, origin: str, amount: int) -> Account:
        self._validate_amount(amount)
        amount_decimal = Decimal(amount)
        account = await self._repo.get_for_update(origin)
        if account is None:
            logger.warning("account_not_found", account_id=origin)
            raise AccountNotFound(origin)

        current = _to_int_balance(account.balance)
        self._validate_limit(origin, current, amount)
        updated = await self._repo.record_transaction(
            origin,
            -amount_decimal,
            "withdraw",
        )
        new_balance_int = _to_int_balance(updated.balance)
        logger.info(
            "withdraw_completed",
            origin=origin,
            amount=amount,
            previous_balance=current,
            new_balance=new_balance_int,
        )
        return Account(id=origin, balance=new_balance_int)

    async def transfer(
        self,
        origin: str,
        destination: str,
        amount: int,
    ) -> tuple[Account, Account]:
        self._validate_amount(amount)
        amount_decimal = Decimal(amount)

        origin_account = await self._repo.get_for_update(origin)
        if origin_account is None:
            logger.warning("account_not_found", account_id=origin)
            raise AccountNotFound(origin)

        origin_balance = _to_int_balance(origin_account.balance)
        self._validate_limit(origin, origin_balance, amount)

        if await self._repo.get(destination) is None:
            await self._repo.ensure_account(destination)
        await self._repo.lock_accounts_for_update(origin, destination)

        origin_account = await self._repo.get(origin)
        if origin_account is None:
            raise AccountNotFound(origin)

        dest_account = await self._repo.get(destination)
        if dest_account is None:
            raise AccountNotFound(destination)

        dest_balance = _to_int_balance(dest_account.balance)

        updated_origin = await self._repo.record_transaction(
            origin,
            -amount_decimal,
            "transfer_out",
            destination,
        )
        updated_destination = await self._repo.record_transaction(
            destination,
            amount_decimal,
            "transfer_in",
            origin,
        )

        origin_new = _to_int_balance(updated_origin.balance)
        destination_new = _to_int_balance(updated_destination.balance)
        logger.info(
            "transfer_completed",
            origin=origin,
            destination=destination,
            amount=amount,
            origin_previous_balance=origin_balance,
            origin_new_balance=origin_new,
            destination_previous_balance=dest_balance,
            destination_new_balance=destination_new,
        )

        return (
            Account(id=origin, balance=origin_new),
            Account(id=destination, balance=destination_new),
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


def _to_int_balance(balance: Decimal) -> int:
    return int(balance)
