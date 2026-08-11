"""PDF builders for single-tx receipts and full statements (reportlab)."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_INK = colors.HexColor("#15120f")
_MUTED = colors.HexColor("#9c948a")
_ACCENT = colors.HexColor("#e7a339")
_LINE = colors.HexColor("#d9d2c8")
_SURFACE = colors.HexColor("#f7f3ee")


def auth_code(tx_id: str, amount: str, created_at: str) -> str:
    raw = f"{tx_id}|{amount}|{created_at}".encode()
    return hashlib.sha256(raw).hexdigest()[:16].upper()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "brand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=_ACCENT,
            spaceAfter=2,
        ),
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#4fb6b0"),
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=_INK,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=_INK,
            leading=14,
        ),
        "muted": ParagraphStyle(
            "muted",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=_MUTED,
            leading=11,
        ),
        "right": ParagraphStyle(
            "right",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            alignment=TA_RIGHT,
            textColor=_INK,
        ),
        "center": ParagraphStyle(
            "center",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            alignment=TA_CENTER,
            textColor=_MUTED,
        ),
    }


def build_receipt_pdf(presented: dict[str, Any], *, parties: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    s = _styles()
    code = auth_code(
        str(presented.get("id") or ""),
        str(presented.get("amount") or ""),
        str(presented.get("created_at") or ""),
    )
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    story: list[Any] = [
        Paragraph("kalke", s["brand"]),
        Paragraph("DEMO BANCÁRIA", s["eyebrow"]),
        Paragraph("Comprovante de transação", s["h1"]),
        Paragraph(
            "Documento fictício para demonstração — nenhum valor é liquidado de verdade.",
            s["muted"],
        ),
        Spacer(1, 8),
    ]

    rows = [
        ["Tipo", presented.get("title") or presented.get("type") or "—"],
        ["Valor", f"{presented.get('currency', 'USD')} {presented.get('amount', '—')}"],
        ["Data/hora", presented.get("created_at") or "—"],
        ["Status", (presented.get("status") or "completed").capitalize()],
        ["ID", presented.get("id") or "—"],
    ]
    if presented.get("memo"):
        rows.append(["Mensagem", presented["memo"]])
    rows.append(["Instituição", "kalke demo"])
    rows.append(["Código de autenticação", code])

    origin = parties.get("origin") or {}
    dest = parties.get("destination") or {}
    rows.append(
        [
            "Origem",
            _party_line(origin),
        ]
    )
    rows.append(
        [
            "Destino",
            _party_line(dest),
        ]
    )

    table = Table(rows, colWidths=[45 * mm, 125 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), _SURFACE),
                ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Emitido em {issued}", s["muted"]))
    story.append(Paragraph(f"Auth · {code}", s["center"]))
    doc.build(story)
    return buf.getvalue()


def _party_line(party: dict[str, Any]) -> str:
    name = party.get("holder_name") or "—"
    display = party.get("display_number") or party.get("account_id") or ""
    doc = party.get("document_masked") or ""
    bits = [str(name)]
    if display:
        bits.append(str(display))
    if doc:
        bits.append(str(doc))
    return " · ".join(bits)


def build_statement_pdf(
    *,
    holder_name: str,
    account_display: str,
    currency: str,
    period_label: str,
    opening_balance: str,
    closing_balance: str,
    rows: list[dict[str, Any]],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    s = _styles()
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story: list[Any] = [
        Paragraph("kalke", s["brand"]),
        Paragraph("DEMO BANCÁRIA · EXTRATO", s["eyebrow"]),
        Paragraph(holder_name or "Titular", s["h1"]),
        Paragraph(f"Conta {account_display} · {currency}", s["body"]),
        Paragraph(f"Período: {period_label}", s["body"]),
        Paragraph(
            f"Saldo inicial: {currency} {opening_balance} · "
            f"Saldo final: {currency} {closing_balance}",
            s["body"],
        ),
        Spacer(1, 8),
    ]

    data = [["Data", "Descrição", "Valor", "Saldo"]]
    for row in rows:
        created = str(row.get("created_at") or "")[:16].replace("T", " ")
        desc = f"{row.get('title') or row.get('type') or ''}<br/>{row.get('subtitle') or ''}"
        data.append(
            [
                created,
                Paragraph(desc, s["body"]),
                f"{row.get('amount') or ''}",
                f"{row.get('balance_after') or ''}",
            ]
        )

    table = Table(data, colWidths=[32 * mm, 85 * mm, 28 * mm, 28 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _SURFACE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
                ("GRID", (0, 0), (-1, -1), 0.3, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "DEMO ONLY — fundos virtuais. Gerado em " + issued,
            s["muted"],
        )
    )
    doc.build(story)
    return buf.getvalue()
