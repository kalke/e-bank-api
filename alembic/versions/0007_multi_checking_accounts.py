"""Allow multiple checking accounts per user.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-11 01:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_accounts_owner_kind", "accounts", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_accounts_owner_kind",
        "accounts",
        ["owner_subject", "kind"],
    )
