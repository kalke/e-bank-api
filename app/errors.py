class DomainError(Exception):
    status_code: int = 500

    def __init__(self, message: str):
        super().__init__(message)


class AccountNotFound(DomainError):
    status_code = 404

    def __init__(self, account_id: str):
        self.account_id = account_id
        super().__init__(f"Account {account_id} not found")


class InsufficientFunds(DomainError):
    status_code = 400

    def __init__(self, account_id: str):
        self.account_id = account_id
        super().__init__(f"Account {account_id} has insufficient funds")


class InvalidAmount(DomainError):
    status_code = 400

    def __init__(self, amount: int):
        self.amount = amount
        self.status_code = 400
        super().__init__(f"Amount {amount} is invalid")
