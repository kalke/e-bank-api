class AccountNotFound(Exception):
    pass


class InsufficientFunds(Exception):
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(account_id)


class InvalidAmount(Exception):
    pass
