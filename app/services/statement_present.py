"""Presentation layer for statement rows — never mutates ledger data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.money import Money
from app.domain.validation import mask_document

_PRESERVE = re.compile(
    r"^(LTDA|LTDA\.|S\.?A\.?|ME|EIRELI|EPP|SA|S/A|CPI|CNPJ|CPF)$",
    re.IGNORECASE,
)
_PARTICLES = {"da", "de", "do", "dos", "das", "e", "di", "du", "del", "della"}
_CONTROLS = re.compile(r"[\x00-\x1f\x7f]+")
_MULTI_SPACE = re.compile(r"\s+")

# Future-ready aliases (no ledger rows yet).
_TYPE_META: dict[str, dict[str, str]] = {
    "transfer_in": {
        "title_pt": "Transferência recebida",
        "title_en": "Transfer received",
        "badge": "transfer_in",
        "direction": "in",
    },
    "transfer_out": {
        "title_pt": "Transferência enviada",
        "title_en": "Transfer sent",
        "badge": "transfer_out",
        "direction": "out",
    },
    "demo_grant": {
        "title_pt": "Crédito demo",
        "title_en": "Demo credit",
        "badge": "grant",
        "direction": "in",
    },
    "deposit": {
        "title_pt": "Depósito",
        "title_en": "Deposit",
        "badge": "grant",
        "direction": "in",
    },
    "withdraw": {
        "title_pt": "Saque",
        "title_en": "Withdrawal",
        "badge": "withdraw",
        "direction": "out",
    },
    # Reserved labels (unused until ledger emits them)
    "pix_in": {
        "title_pt": "Pix recebido",
        "title_en": "Pix received",
        "badge": "transfer_in",
        "direction": "in",
    },
    "pix_out": {
        "title_pt": "Pix enviado",
        "title_en": "Pix sent",
        "badge": "transfer_out",
        "direction": "out",
    },
    "boleto": {
        "title_pt": "Pagamento de boleto",
        "title_en": "Bank slip payment",
        "badge": "other",
        "direction": "out",
    },
    "fee": {
        "title_pt": "Tarifa",
        "title_en": "Fee",
        "badge": "other",
        "direction": "out",
    },
    "interest": {
        "title_pt": "Rendimento",
        "title_en": "Interest / yield",
        "badge": "grant",
        "direction": "in",
    },
    "refund": {
        "title_pt": "Estorno",
        "title_en": "Refund",
        "badge": "grant",
        "direction": "in",
    },
}


@dataclass(frozen=True)
class CounterpartyContext:
    account_id: str | None = None
    display_number: str | None = None
    holder_name: str | None = None
    document_number: str | None = None


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = _CONTROLS.sub(" ", str(raw))
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text


def title_case_name(raw: str | None) -> str:
    cleaned = clean_text(raw)
    if not cleaned:
        return ""
    parts: list[str] = []
    for i, token in enumerate(cleaned.split(" ")):
        if not token:
            continue
        if _PRESERVE.match(token) or any(ch.isdigit() for ch in token):
            parts.append(token.upper() if _PRESERVE.match(token) else token)
            continue
        lower = token.lower()
        if i > 0 and lower in _PARTICLES:
            parts.append(lower)
            continue
        parts.append(lower[:1].upper() + lower[1:] if lower else token)
    return " ".join(parts)


def _meta_for(tx_type: str, amount: Decimal) -> dict[str, str]:
    key = (tx_type or "").strip().lower()
    if key in _TYPE_META:
        return dict(_TYPE_META[key])
    if amount >= 0:
        return {
            "title_pt": "Entrada",
            "title_en": "Incoming",
            "badge": "other",
            "direction": "in",
        }
    return {
        "title_pt": "Saída",
        "title_en": "Outgoing",
        "badge": "other",
        "direction": "out",
    }


def present_transaction(
    *,
    tx_id: str,
    account_id: str,
    amount: Decimal | str,
    tx_type: str,
    counterparty_account_id: str | None,
    memo: str | None,
    created_at: Any,
    currency: str = "USD",
    counterparty: CounterpartyContext | None = None,
    lang: str = "pt",
) -> dict[str, Any]:
    money = Money(amount)
    amt = money.amount
    meta = _meta_for(tx_type, amt)
    # Prefer signed amount for direction when type is ambiguous.
    if meta["direction"] == "in" and amt < 0:
        meta["direction"] = "out"
    if meta["direction"] == "out" and amt > 0 and tx_type not in _TYPE_META:
        meta["direction"] = "in"

    title = meta["title_pt"] if lang != "en" else meta["title_en"]
    cp = counterparty or CounterpartyContext()
    name = title_case_name(cp.holder_name)
    display = clean_text(cp.display_number) or clean_text(counterparty_account_id)
    memo_clean = clean_text(memo)

    if meta["direction"] == "in" and name:
        subtitle = f"de {name}" if lang != "en" else f"from {name}"
    elif meta["direction"] == "out" and name:
        subtitle = f"para {name}" if lang != "en" else f"to {name}"
    elif display:
        subtitle = display
    elif memo_clean:
        subtitle = memo_clean
    else:
        subtitle = "—"

    created = (
        created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    )

    return {
        "id": tx_id,
        "account_id": account_id,
        "amount": money.as_str(),
        "signed_amount": money.as_str(),
        "type": tx_type,
        "counterparty_account_id": counterparty_account_id,
        "memo": memo_clean or None,
        "created_at": created,
        "currency": currency or "USD",
        "direction": meta["direction"],
        "title": title,
        "title_key": (tx_type or "other").lower(),
        "subtitle": subtitle,
        "badge": meta["badge"],
        "counterparty_display": display or None,
        "counterparty_name": name or None,
        "counterparty_document_masked": mask_document(cp.document_number),
        "status": "completed",
    }


def type_filter_match(tx_type: str, filter_type: str | None) -> bool:
    if not filter_type or filter_type in {"all", ""}:
        return True
    key = filter_type.strip().lower()
    t = (tx_type or "").lower()
    if key == "transfer":
        return t in {"transfer_in", "transfer_out", "pix_in", "pix_out"}
    if key == "grant":
        return t in {"demo_grant", "deposit", "interest", "refund"}
    if key == "withdraw":
        return t == "withdraw"
    return t == key
