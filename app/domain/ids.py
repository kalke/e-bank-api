"""Public resource identifiers (UUID v4 as strings)."""

from __future__ import annotations

from uuid import uuid4


def new_uuid() -> str:
    """Return a new UUID v4 string for public/API-facing resource ids."""
    return str(uuid4())
