"""Per-account onboarding status and session binding.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12 18:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "onboarding_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE accounts AS a
            SET onboarding_status = COALESCE(u.onboarding_status, 'not_started')
            FROM users AS u
            WHERE a.owner_subject = u.subject
              AND a.kind = 'checking'
            """
        )
    )

    op.add_column(
        "onboarding_sessions",
        sa.Column("account_id", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_onboarding_sessions_account_id",
        "onboarding_sessions",
        "accounts",
        ["account_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE onboarding_sessions AS s
            SET account_id = (
                SELECT a.id
                FROM accounts AS a
                WHERE a.owner_subject = s.subject
                  AND a.kind = 'checking'
                ORDER BY a.created_at ASC, a.id ASC
                LIMIT 1
            )
            WHERE s.account_id IS NULL
            """
        )
    )
    op.create_index(
        "ix_onboarding_sessions_account_id_created_at",
        "onboarding_sessions",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_onboarding_sessions_account_id_created_at",
        table_name="onboarding_sessions",
    )
    op.drop_constraint(
        "fk_onboarding_sessions_account_id",
        "onboarding_sessions",
        type_="foreignkey",
    )
    op.drop_column("onboarding_sessions", "account_id")
    op.drop_column("accounts", "onboarding_status")
