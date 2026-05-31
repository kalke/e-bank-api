from app.store import InMemoryStore


def test_get_balance_returns_none_for_missing_account() -> None:
    store = InMemoryStore()
    assert store.get_balance("999") is None


def test_set_and_get_balance() -> None:
    store = InMemoryStore()
    store.set_balance("100", 42)
    assert store.get_balance("100") == 42


def test_exists() -> None:
    store = InMemoryStore()
    assert store.exists("100") is False
    store.set_balance("100", 10)
    assert store.exists("100") is True


def test_clear_removes_all_accounts() -> None:
    store = InMemoryStore()
    store.set_balance("100", 10)
    store.set_balance("200", 5)
    store.clear()
    assert store.exists("100") is False
    assert store.exists("200") is False
