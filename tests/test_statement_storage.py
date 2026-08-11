"""Unit tests for receipt PDF S3 helpers (no AWS calls)."""

from app.services.statement_storage import BankPDFStore, receipt_key


def test_receipt_key() -> None:
    assert receipt_key("acc", "tx-1") == "receipts/acc/tx-1.pdf"


def test_store_disabled_without_bucket() -> None:
    store = BankPDFStore(bucket="")
    assert not store.enabled
    assert store.get("receipts/a/b.pdf") is None
    store.put("receipts/a/b.pdf", b"%PDF")  # no-op when disabled
