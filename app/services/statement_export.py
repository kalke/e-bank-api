"""CSV / filtered statement export helpers."""

from __future__ import annotations

import csv
import io
from typing import Any


EXPORT_MAX_ROWS = 500


def build_statement_csv(rows: list[dict[str, Any]]) -> bytes:
    """UTF-8 BOM + semicolon delimiter (BR spreadsheet friendly)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        [
            "id",
            "created_at",
            "type",
            "title",
            "subtitle",
            "direction",
            "amount",
            "currency",
            "memo",
            "counterparty_name",
            "counterparty_display",
            "balance_after",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("id") or "",
                row.get("created_at") or "",
                row.get("type") or "",
                row.get("title") or "",
                row.get("subtitle") or "",
                row.get("direction") or "",
                row.get("amount") or "",
                row.get("currency") or "USD",
                row.get("memo") or "",
                row.get("counterparty_name") or "",
                row.get("counterparty_display") or "",
                row.get("balance_after") or "",
            ]
        )
    # Excel on Windows expects BOM for UTF-8
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
