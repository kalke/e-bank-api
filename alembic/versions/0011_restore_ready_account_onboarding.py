"""Restore ready onboarding_status for accounts that already received a grant.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-12 20:00:00.000000

0008/0010 copied users.onboarding_status onto every checking row. A holder-level
in_progress restart then froze accounts that already had a welcome grant.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE accounts AS a
            SET onboarding_status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM onboarding_sessions AS s
                    WHERE s.account_id = a.id
                      AND s.status = 'approved_demo'
                ) THEN 'completed'
                WHEN EXISTS (
                    SELECT 1 FROM onboarding_sessions AS s
                    WHERE s.account_id = a.id
                      AND s.status = 'skipped'
                ) THEN 'skipped'
                WHEN EXISTS (
                    SELECT 1 FROM transactions AS t
                    WHERE t.account_id = a.id
                      AND t.type = 'demo_grant'
                ) THEN 'skipped'
                ELSE a.onboarding_status
            END
            WHERE a.kind = 'checking'
              AND a.onboarding_status IN ('not_started', 'in_progress')
            """
        )
    )


def downgrade() -> None:
    pass
