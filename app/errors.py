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

    def __init__(self, amount: int | str):
        self.amount = amount
        super().__init__(f"Amount {amount} is invalid")


class ForbiddenAccountAccess(DomainError):
    status_code = 403

    def __init__(self, account_id: str = ""):
        self.account_id = account_id
        msg = (
            f"Access denied for account {account_id}" if account_id else "Access denied"
        )
        super().__init__(msg)


class TransferLimitExceeded(DomainError):
    status_code = 400

    def __init__(self, amount: str, limit: str):
        super().__init__(f"Amount {amount} exceeds limit {limit}")


class OnboardingError(DomainError):
    status_code = 400


class DemoAlreadyBootstrapped(DomainError):
    """Informational — bootstrap is idempotent; not raised in happy path."""

    status_code = 200
