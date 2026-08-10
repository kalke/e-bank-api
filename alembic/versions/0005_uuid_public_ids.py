"""UUID v4 public ids for transactions; remap chk_* account PKs to UUID.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-10 22:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "transactions",
        sa.Column("public_id", sa.String(length=36), nullable=True),
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE transactions SET public_id = gen_random_uuid()::text "
                "WHERE public_id IS NULL"
            )
        )
        # Drop FKs that block remapping account primary keys.
        op.drop_constraint(
            "transactions_account_id_fkey",
            "transactions",
            type_="foreignkey",
        )
        op.execute(
            sa.text(
                """
                CREATE TEMP TABLE account_id_map AS
                SELECT id AS old_id, gen_random_uuid()::text AS new_id
                FROM accounts
                WHERE id LIKE 'chk_%'
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE transactions AS t
                SET account_id = m.new_id
                FROM account_id_map AS m
                WHERE t.account_id = m.old_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE transactions AS t
                SET counterparty_account_id = m.new_id
                FROM account_id_map AS m
                WHERE t.counterparty_account_id = m.old_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE ledger_postings AS p
                SET ledger_account_id = m.new_id
                FROM account_id_map AS m
                WHERE p.ledger_account_id = m.old_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE ledger_accounts AS la
                SET id = m.new_id
                FROM account_id_map AS m
                WHERE la.id = m.old_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE accounts AS a
                SET id = m.new_id
                FROM account_id_map AS m
                WHERE a.id = m.old_id
                """
            )
        )
        op.create_foreign_key(
            "transactions_account_id_fkey",
            "transactions",
            "accounts",
            ["account_id"],
            ["id"],
        )
    else:
        import uuid

        connection = op.get_bind()
        rows = connection.execute(
            sa.text("SELECT id FROM transactions WHERE public_id IS NULL")
        ).fetchall()
        for (txn_id,) in rows:
            connection.execute(
                sa.text("UPDATE transactions SET public_id = :pid WHERE id = :id"),
                {"pid": str(uuid.uuid4()), "id": txn_id},
            )
        chk_rows = connection.execute(
            sa.text("SELECT id FROM accounts WHERE id LIKE 'chk_%'")
        ).fetchall()
        for (old_id,) in chk_rows:
            new_id = str(uuid.uuid4())
            connection.execute(
                sa.text("UPDATE transactions SET account_id = :n WHERE account_id = :o"),
                {"n": new_id, "o": old_id},
            )
            connection.execute(
                sa.text(
                    "UPDATE transactions SET counterparty_account_id = :n "
                    "WHERE counterparty_account_id = :o"
                ),
                {"n": new_id, "o": old_id},
            )
            connection.execute(
                sa.text(
                    "UPDATE ledger_postings SET ledger_account_id = :n "
                    "WHERE ledger_account_id = :o"
                ),
                {"n": new_id, "o": old_id},
            )
            connection.execute(
                sa.text("UPDATE ledger_accounts SET id = :n WHERE id = :o"),
                {"n": new_id, "o": old_id},
            )
            connection.execute(
                sa.text("UPDATE accounts SET id = :n WHERE id = :o"),
                {"n": new_id, "o": old_id},
            )

    op.alter_column(
        "transactions",
        "public_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.create_index(
        "ix_transactions_public_id",
        "transactions",
        ["public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_public_id", table_name="transactions")
    op.drop_column("transactions", "public_id")
