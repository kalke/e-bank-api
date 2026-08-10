"""holders, account numbers, double-entry ledger

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNT_NUMBER_START = 100000


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"CREATE SEQUENCE IF NOT EXISTS account_number_seq "
                f"START WITH {ACCOUNT_NUMBER_START} INCREMENT BY 1"
            )
        )

    op.create_table(
        "holders",
        sa.Column(
            "subject",
            sa.String(length=128),
            sa.ForeignKey("users.subject"),
            primary_key=True,
        ),
        sa.Column("full_name", sa.String(length=256), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("document_type", sa.String(length=32), nullable=True),
        sa.Column("document_number", sa.String(length=32), nullable=True),
        sa.Column("cep", sa.String(length=8), nullable=True),
        sa.Column("street", sa.String(length=256), nullable=True),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("complement", sa.String(length=128), nullable=True),
        sa.Column("neighborhood", sa.String(length=128), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_holders_document_number", "holders", ["document_number"])

    op.add_column(
        "accounts",
        sa.Column("account_number", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("digit", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "balance_cached",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_accounts_account_number",
        "accounts",
        ["account_number"],
        unique=True,
    )

    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO ledger_accounts (id, code, name, kind) VALUES "
            "('sys_cash', 'cash', 'System cash', 'asset')"
        )
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("actor_subject", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True, unique=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "ledger_postings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "journal_id",
            sa.String(length=36),
            sa.ForeignKey("journal_entries.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "ledger_account_id",
            sa.String(length=64),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("side", sa.String(length=6), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    op.add_column(
        "onboarding_sessions",
        sa.Column("draft_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("onboarding_sessions", "draft_json")
    op.drop_table("ledger_postings")
    op.drop_table("journal_entries")
    op.drop_table("ledger_accounts")
    op.drop_index("ix_accounts_account_number", table_name="accounts")
    op.drop_column("accounts", "balance_cached")
    op.drop_column("accounts", "digit")
    op.drop_column("accounts", "account_number")
    op.drop_index("ix_holders_document_number", table_name="holders")
    op.drop_table("holders")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP SEQUENCE IF EXISTS account_number_seq"))
