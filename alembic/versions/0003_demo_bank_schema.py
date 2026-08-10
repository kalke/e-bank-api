"""demo bank schema: users, ownership, onboarding, grants, audit

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("subject", sa.String(length=128), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column(
            "onboarding_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("demo_credited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.add_column(
        "accounts",
        sa.Column("owner_subject", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="checking",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "overdraft_limit",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_foreign_key(
        "fk_accounts_owner_subject",
        "accounts",
        "users",
        ["owner_subject"],
        ["subject"],
    )
    op.create_index("ix_accounts_owner_subject", "accounts", ["owner_subject"])
    op.create_unique_constraint(
        "uq_accounts_owner_kind",
        "accounts",
        ["owner_subject", "kind"],
    )

    op.add_column(
        "transactions",
        sa.Column("actor_subject", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
    )
    op.add_column("transactions", sa.Column("memo", sa.Text(), nullable=True))

    op.create_table(
        "onboarding_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject"], ["users.subject"]),
    )
    op.create_index(
        "ix_onboarding_sessions_subject",
        "onboarding_sessions",
        ["subject"],
    )

    op.create_table(
        "onboarding_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=False),
        sa.Column("pde_extraction_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["onboarding_sessions.id"]),
    )
    op.create_index(
        "ix_onboarding_documents_session_id",
        "onboarding_documents",
        ["session_id"],
    )

    op.create_table(
        "consents",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject"], ["users.subject"]),
        sa.UniqueConstraint(
            "subject",
            "policy_version",
            name="uq_consents_subject_policy",
        ),
    )
    op.create_index("ix_consents_subject", "consents", ["subject"])

    op.create_table(
        "demo_grants",
        sa.Column("subject", sa.String(length=128), primary_key=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["subject"], ["users.subject"]),
    )


def downgrade() -> None:
    op.drop_table("demo_grants")
    op.drop_index("ix_consents_subject", table_name="consents")
    op.drop_table("consents")
    op.drop_index(
        "ix_onboarding_documents_session_id",
        table_name="onboarding_documents",
    )
    op.drop_table("onboarding_documents")
    op.drop_index(
        "ix_onboarding_sessions_subject",
        table_name="onboarding_sessions",
    )
    op.drop_table("onboarding_sessions")

    op.drop_column("transactions", "memo")
    op.drop_column("transactions", "idempotency_key")
    op.drop_column("transactions", "request_id")
    op.drop_column("transactions", "actor_subject")

    op.drop_constraint("uq_accounts_owner_kind", "accounts", type_="unique")
    op.drop_index("ix_accounts_owner_subject", table_name="accounts")
    op.drop_constraint("fk_accounts_owner_subject", "accounts", type_="foreignkey")
    op.drop_column("accounts", "overdraft_limit")
    op.drop_column("accounts", "status")
    op.drop_column("accounts", "currency")
    op.drop_column("accounts", "kind")
    op.drop_column("accounts", "owner_subject")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
