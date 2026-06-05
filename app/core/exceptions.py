class DuplicateRequestException(Exception):
    """Raised when an idempotency key is already being processed."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            "A request with this key is already being processed",
        )


class IdempotencyStorageException(Exception):
    """Raised when the idempotency store (Redis) is unavailable."""

    def __init__(self, message: str = "Idempotency storage is unavailable") -> None:
        super().__init__(message)
