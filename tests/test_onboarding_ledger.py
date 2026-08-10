from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain.validation import (
    age_years,
    format_account_display,
    mask_document,
    parse_account_display,
    require_adult,
    validate_cep,
    validate_cnpj,
    validate_cpf,
    validate_document,
    validate_email,
    validate_phone,
)
from app.errors import OnboardingError
from app.models.ledger import JournalEntry, LedgerPosting
from app.services.account_number import AccountNumberGenerator
from app.services.cep import CepLookup
from app.services.ledger import SYS_CASH_ID, LedgerError, LedgerService, PostingLine

VALID_CPF = "39053344705"
# Valid CNPJ check digits
VALID_CNPJ = "11222333000181"


def test_cpf_and_age() -> None:
    assert validate_cpf(VALID_CPF) == VALID_CPF
    assert age_years(date(2000, 1, 1), today=date(2026, 8, 10)) == 26
    with pytest.raises(OnboardingError):
        require_adult(date(2015, 1, 1), today=date(2026, 8, 10))
    with pytest.raises(OnboardingError):
        validate_cpf("11111111111")
    with pytest.raises(OnboardingError):
        validate_cpf("12345678901")


def test_cnpj_and_document_dispatch() -> None:
    assert validate_cnpj(VALID_CNPJ) == VALID_CNPJ
    assert validate_document(VALID_CPF) == ("cpf", VALID_CPF)
    assert validate_document(VALID_CNPJ) == ("cnpj", VALID_CNPJ)
    with pytest.raises(OnboardingError):
        validate_document("123")


def test_cep_email_phone() -> None:
    assert validate_cep("01310-100") == "01310100"
    assert validate_email("  Foo@Example.COM ") == "foo@example.com"
    assert validate_phone("(11) 98765-4321") == "11987654321"
    with pytest.raises(OnboardingError):
        validate_cep("123")
    with pytest.raises(OnboardingError):
        validate_email("not-an-email")
    with pytest.raises(OnboardingError):
        validate_phone("123")


def test_account_display_roundtrip() -> None:
    assert format_account_display(100123, 4) == "100123-4"
    assert parse_account_display("100123-4") == (100123, 4)
    assert parse_account_display("1001234") == (100123, 4)
    assert mask_document(VALID_CPF) == "***.***.***-05"
    assert mask_document(None) is None
    with pytest.raises(OnboardingError):
        parse_account_display("1")


@pytest.mark.asyncio
async def test_account_number_generator(db_session) -> None:
    gen = AccountNumberGenerator(db_session)
    a = await gen.next_identity()
    b = await gen.next_identity()
    assert a.account_number >= 1
    assert b.account_number == a.account_number + 1
    assert 0 <= a.digit <= 9
    assert 0 <= b.digit <= 9
    assert 0 <= a.digit <= 9
    assert 0 <= b.digit <= 9


@pytest.mark.asyncio
async def test_ledger_balanced_and_cache(db_session, account_repo) -> None:
    from app.models.account import Account

    await account_repo.create("ledger-cust-1", Decimal("0"))
    account = await db_session.get(Account, "ledger-cust-1")
    assert account is not None
    ledger = LedgerService(db_session)
    await ledger.ensure_customer_ledger_account(account)

    await ledger.post(
        entry_type="welcome_grant",
        actor_subject="sub-1",
        lines=[
            PostingLine(SYS_CASH_ID, "debit", Decimal("100.00")),
            PostingLine(account.id, "credit", Decimal("100.00")),
        ],
        idempotency_key="welcome-1",
    )
    await db_session.refresh(account)
    assert account.balance_cached == Decimal("100.00")
    assert await ledger.customer_balance(account.id) == Decimal("100.00")

    with pytest.raises(LedgerError, match="not balanced"):
        await ledger.post(
            entry_type="transfer",
            actor_subject="sub-1",
            lines=[
                PostingLine(account.id, "debit", Decimal("10.00")),
                PostingLine(SYS_CASH_ID, "credit", Decimal("5.00")),
            ],
            idempotency_key="bad-1",
        )


@pytest.mark.asyncio
async def test_ledger_idempotent_replay(db_session, account_repo) -> None:
    from app.models.account import Account
    from app.services.ledger import IdempotentReplay

    await account_repo.create("ledger-cust-2", Decimal("0"))
    account = await db_session.get(Account, "ledger-cust-2")
    assert account is not None
    ledger = LedgerService(db_session)
    await ledger.ensure_customer_ledger_account(account)

    first = await ledger.post(
        entry_type="welcome_grant",
        actor_subject="sub-2",
        lines=[
            PostingLine(SYS_CASH_ID, "debit", Decimal("50.00")),
            PostingLine(account.id, "credit", Decimal("50.00")),
        ],
        idempotency_key="idem-ledger-1",
    )
    with pytest.raises(IdempotentReplay) as exc:
        await ledger.post(
            entry_type="welcome_grant",
            actor_subject="sub-2",
            lines=[
                PostingLine(SYS_CASH_ID, "debit", Decimal("50.00")),
                PostingLine(account.id, "credit", Decimal("50.00")),
            ],
            idempotency_key="idem-ledger-1",
        )
    assert exc.value.journal_id == first.id
    await db_session.refresh(account)
    assert account.balance_cached == Decimal("50.00")


@pytest.mark.asyncio
async def test_cep_lookup_success_and_404() -> None:
    lookup = CepLookup()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "street": "Av Paulista",
        "neighborhood": "Bela Vista",
        "city": "São Paulo",
        "state": "SP",
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.cep.httpx.AsyncClient", return_value=mock_client):
        result = await lookup.lookup("01310-100")
    assert result["cep"] == "01310100"
    assert result["city"] == "São Paulo"

    mock_resp.status_code = 404
    with (
        patch("app.services.cep.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(OnboardingError, match="not found"),
    ):
        await lookup.lookup("01310100")


def _open(client: TestClient) -> dict:
    client.post("/v1/onboarding/start")
    skip = client.post("/v1/onboarding/skip")
    assert skip.status_code == 200
    return skip.json()


def test_money_gated_until_onboarding(client: TestClient) -> None:
    assert client.get("/v1/me/account").status_code == 400
    assert (
        client.post(
            "/v1/me/transfer",
            headers={"Idempotency-Key": "g1"},
            json={"destination_account_id": "x", "amount": "1.00"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/me/withdraw",
            headers={"Idempotency-Key": "g2"},
            json={"amount": "1.00"},
        ).status_code
        == 400
    )


def test_complete_requires_terms(client: TestClient) -> None:
    client.post("/v1/onboarding/start")
    response = client.post(
        "/v1/onboarding/complete",
        json={
            "full_name": "Maria Silva",
            "birth_date": "1990-05-20",
            "document_number": VALID_CPF,
            "cep": "01310100",
            "street": "Av Paulista",
            "number": "1000",
            "email": "maria@example.com",
            "phone": "11987654321",
            "terms_accepted": False,
        },
    )
    assert response.status_code == 400


def test_resolve_by_account_number(client: TestClient) -> None:
    opened = _open(client)
    resolved = client.post(
        "/v1/me/transfers/resolve",
        json={"account": opened["display_number"]},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["account_display"] == opened["display_number"]
    assert body["holder_name"]


def test_account_detail_by_display(client: TestClient) -> None:
    opened = _open(client)
    detail = client.get(f"/v1/me/accounts/{opened['display_number']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == opened["id"]
    assert detail.json()["balance"] == "10000.00"


def test_transfer_updates_balance_cached(client: TestClient) -> None:
    opened = _open(client)
    peer = client.post(
        "/event",
        json={"type": "deposit", "destination": "peer-chk", "amount": 500},
    )
    assert peer.status_code == 201

    xfer = client.post(
        "/v1/me/transfer",
        headers={"Idempotency-Key": "cache-xfer-1"},
        json={
            "destination_account_id": "peer-chk",
            "amount": "10.00",
            "memo": "peer",
        },
    )
    assert xfer.status_code == 200, xfer.json()
    assert xfer.json()["origin"]["balance"] == "9990.00"
    me = client.get("/v1/me/account")
    assert me.json()["id"] == opened["id"]
    assert me.json()["balance"] == "9990.00"
    assert me.json()["display_number"] == opened["display_number"]


@pytest.mark.asyncio
async def test_transfer_journal_debits_equal_credits(
    client: TestClient, db_session
) -> None:
    _open(client)
    client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-bal", "amount": 1},
    )
    client.post(
        "/v1/me/transfer",
        headers={"Idempotency-Key": "bal-xfer"},
        json={"destination_account_id": "dest-bal", "amount": "12.34"},
    )

    journals = (await db_session.execute(select(JournalEntry))).scalars().all()
    assert journals
    for journal in journals:
        rows = (
            await db_session.execute(
                select(
                    LedgerPosting.side,
                    func.sum(LedgerPosting.amount),
                )
                .where(LedgerPosting.journal_id == journal.id)
                .group_by(LedgerPosting.side)
            )
        ).all()
        amounts = {side: Decimal(str(total)) for side, total in rows}
        assert amounts.get("debit") == amounts.get("credit")


def test_transfer_requires_idempotency_key(client: TestClient) -> None:
    _open(client)
    client.post(
        "/event",
        json={"type": "deposit", "destination": "dest-idem", "amount": 1},
    )
    response = client.post(
        "/v1/me/transfer",
        json={"destination_account_id": "dest-idem", "amount": "1.00"},
    )
    assert response.status_code == 400


def test_cep_endpoint_invalid(client: TestClient) -> None:
    response = client.get("/v1/cep/123")
    assert response.status_code == 400
