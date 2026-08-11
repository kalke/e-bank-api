"""Unit tests for statement PDF S3 key helpers (no AWS calls)."""

from app.services.statement_storage import get_or_create_pdf, receipt_key, statement_key


def test_receipt_key() -> None:
    assert receipt_key("acc", "tx-1") == "receipts/acc/tx-1.pdf"


def test_statement_key_stable() -> None:
    filters = {"from": "2026-01-01", "to": "2026-01-31", "type": "all"}
    a = statement_key("acc", filters)
    b = statement_key("acc", dict(reversed(list(filters.items()))))
    assert a == b
    assert a.startswith("statements/acc/")
    assert a.endswith(".pdf")


def test_get_or_create_without_bucket() -> None:
    calls = {"n": 0}

    def gen() -> bytes:
        calls["n"] += 1
        return b"%PDF-demo"

    out = get_or_create_pdf(
        key="receipts/a/b.pdf",
        generate=gen,
        event_generated="bank.receipt.generated",
        event_hit="bank.receipt.cache_hit",
    )
    assert out == b"%PDF-demo"
    assert calls["n"] == 1
