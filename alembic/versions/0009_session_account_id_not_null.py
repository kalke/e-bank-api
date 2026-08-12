"""Require onboarding_sessions.account_id after 0008 backfill.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text("SELECT COUNT(*) FROM onboarding_sessions WHERE account_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"onboarding_sessions.account_id has {orphans} NULL row(s); "
            "backfill before applying 0009"
        )
    with op.batch_alter_table("onboarding_sessions") as batch_op:
        batch_op.alter_column(
            "account_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("onboarding_sessions") as batch_op:
        batch_op.alter_column(
            "account_id",
            existing_type=sa.String(length=64),
            nullable=True,
        )
