from datetime import UTC, datetime
from decimal import Decimal

from app.services.statement_export import build_statement_csv
from app.services.statement_pdf import auth_code, build_receipt_pdf, build_statement_pdf
from app.services.statement_present import (
    CounterpartyContext,
    clean_text,
    present_transaction,
    title_case_name,
)


def test_title_case_name() -> None:
    assert title_case_name("MARIA DA SILVA") == "Maria da Silva"
    assert title_case_name("JOAO LTDA") == "Joao LTDA"
    assert title_case_name("  ana   paula  ") == "Ana Paula"
    assert clean_text("hi\x00there") == "hi there"


def test_present_transfer_out() -> None:
    row = present_transaction(
        tx_id="abc",
        account_id="acc1",
        amount=Decimal("-12.50"),
        tx_type="transfer_out",
        counterparty_account_id="acc2",
        memo="  hello  ",
        created_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        currency="USD",
        counterparty=CounterpartyContext(
            account_id="acc2",
            display_number="100-1",
            holder_name="PEDRO DE SOUZA",
            document_number="39053344705",
        ),
    )
    assert row["direction"] == "out"
    assert row["badge"] == "transfer_out"
    assert row["title"] == "Transferência enviada"
    assert "Pedro" in row["subtitle"]
    assert row["memo"] == "hello"
    assert row["counterparty_document_masked"] is not None


def test_present_demo_grant() -> None:
    row = present_transaction(
        tx_id="g1",
        account_id="acc1",
        amount="10000.00",
        tx_type="demo_grant",
        counterparty_account_id=None,
        memo=None,
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert row["direction"] == "in"
    assert row["badge"] == "grant"
    assert row["title"] == "Crédito demo"


def test_csv_delimiter_and_bom() -> None:
    body = build_statement_csv(
        [
            {
                "id": "1",
                "created_at": "2026-01-01",
                "type": "demo_grant",
                "title": "Crédito demo",
                "subtitle": "—",
                "direction": "in",
                "amount": "10.00",
                "currency": "USD",
                "memo": None,
                "counterparty_name": None,
                "counterparty_display": None,
                "balance_after": "10.00",
            }
        ]
    )
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert ";" in text.splitlines()[0]
    assert "balance_after" in text.splitlines()[0]


def test_receipt_pdf_magic() -> None:
    presented = present_transaction(
        tx_id="tx-1",
        account_id="a",
        amount="-5.00",
        tx_type="transfer_out",
        counterparty_account_id="b",
        memo="x",
        created_at="2026-02-01T10:00:00+00:00",
        counterparty=CounterpartyContext(holder_name="Bob", display_number="2-0"),
    )
    pdf = build_receipt_pdf(
        presented,
        parties={
            "origin": {"holder_name": "Alice", "display_number": "1-0"},
            "destination": {"holder_name": "Bob", "display_number": "2-0"},
        },
    )
    assert pdf.startswith(b"%PDF")
    assert auth_code("tx-1", "-5.00", "2026-02-01T10:00:00+00:00")


def test_statement_pdf_magic() -> None:
    pdf = build_statement_pdf(
        holder_name="Maria",
        account_display="1-0",
        currency="USD",
        period_label="all",
        opening_balance="0.00",
        closing_balance="10.00",
        rows=[
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "title": "Crédito demo",
                "subtitle": "—",
                "amount": "10.00",
                "balance_after": "10.00",
                "type": "demo_grant",
            }
        ],
    )
    assert pdf.startswith(b"%PDF")
