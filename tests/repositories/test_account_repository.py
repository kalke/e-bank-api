from decimal import Decimal

from app.repositories.account_repository import AccountRepository


async def test_get_returns_none_for_unknown_account(
    account_repo: AccountRepository,
) -> None:
    assert await account_repo.get("unknown") is None


async def test_create_then_get_returns_account_with_correct_balance(
    account_repo: AccountRepository,
) -> None:
    created = await account_repo.create("100", Decimal("42"))
    assert created.id == "100"
    assert created.balance == Decimal("42")

    fetched = await account_repo.get("100")
    assert fetched is not None
    assert fetched.id == "100"
    assert fetched.balance == Decimal("42")


async def test_record_transaction_persists_new_balance(
    account_repo: AccountRepository,
    db_session,
) -> None:
    await account_repo.create("100", Decimal("10"))
    updated = await account_repo.record_transaction("100", Decimal("15"), "deposit")
    assert updated.balance == Decimal("25")

    await db_session.commit()

    refetched = await account_repo.get("100")
    assert refetched is not None
    assert refetched.balance == Decimal("25")


async def test_get_for_update_works_inside_transaction(
    account_repo: AccountRepository,
) -> None:
    await account_repo.create("100", Decimal("50"))
    locked = await account_repo.get_for_update("100")
    assert locked is not None
    assert locked.balance == Decimal("50")


async def test_delete_all_removes_every_account(
    account_repo: AccountRepository,
) -> None:
    await account_repo.create("100", Decimal("10"))
    await account_repo.create("200", Decimal("20"))

    await account_repo.delete_all()

    assert await account_repo.get("100") is None
    assert await account_repo.get("200") is None


async def test_transfer_creates_ledger_entries(
    account_repo: AccountRepository,
) -> None:
    await account_repo.create("100", Decimal("100"))
    await account_repo.ensure_account("200")
    await account_repo.lock_accounts_for_update("100", "200")
    await account_repo.record_transaction("100", Decimal("-30"), "transfer_out", "200")
    await account_repo.record_transaction("200", Decimal("30"), "transfer_in", "100")

    origin = await account_repo.get("100")
    destination = await account_repo.get("200")
    assert origin is not None
    assert destination is not None
    assert origin.balance == Decimal("70")
    assert destination.balance == Decimal("30")
