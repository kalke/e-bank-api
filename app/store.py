class InMemoryStore:
    def __init__(self) -> None:
        self._accounts: dict[str, int] = {}

    def get_balance(self, account_id: str) -> int | None:
        return self._accounts.get(account_id)

    def set_balance(self, account_id: str, balance: int) -> None:
        self._accounts[account_id] = balance

    def exists(self, account_id: str) -> bool:
        return account_id in self._accounts

    def clear(self) -> None:
        self._accounts.clear()
