"""migrate balance column to transaction ledger

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05 00:00:01.000000

For databases created with an older 0001 that included a balance column on
accounts but no transactions table. Fresh installs already have the ledger
schema from the current 0001 and skip this migration entirely.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_transactions_table() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("counterparty_account_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transactions_account_id"),
        "transactions",
        ["account_id"],
        unique=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {col["name"] for col in inspector.get_columns("accounts")}

    if "balance" not in account_columns:
        return

    if "transactions" not in inspector.get_table_names():
        _create_transactions_table()

    op.execute(
        sa.text(
            """
            INSERT INTO transactions (account_id, amount, type, created_at)
            SELECT id, balance, 'deposit', NOW()
            FROM accounts
            WHERE balance <> 0
            """,
        ),
    )
    op.drop_column("accounts", "balance")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {col["name"] for col in inspector.get_columns("accounts")}

    if "balance" in account_columns:
        return

    op.add_column(
        "accounts",
        sa.Column(
            "balance",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE accounts AS a
            SET balance = COALESCE(
                (SELECT SUM(t.amount) FROM transactions t WHERE t.account_id = a.id),
                0
            )
            """,
        ),
    )
    op.execute(sa.text("DELETE FROM transactions"))
