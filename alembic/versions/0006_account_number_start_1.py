"""Restart account numbers at 1.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10 23:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNT_NUMBER_START = 1


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            f"ALTER SEQUENCE IF EXISTS account_number_seq "
            f"RESTART WITH {ACCOUNT_NUMBER_START}"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        sa.text("ALTER SEQUENCE IF EXISTS account_number_seq RESTART WITH 100000")
    )
