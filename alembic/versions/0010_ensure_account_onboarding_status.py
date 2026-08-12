"""Ensure accounts.onboarding_status exists after 0008/0009 drift.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-12 19:55:00.000000

0008 was recorded as applied in production while SELECT still fails with
UndefinedColumnError for accounts.onboarding_status. Re-apply the column
if it is missing; no-op when 0008 actually stuck.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("accounts")}
    if "onboarding_status" in columns:
        return

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


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("accounts")}
    if "onboarding_status" not in columns:
        return
    op.drop_column("accounts", "onboarding_status")
