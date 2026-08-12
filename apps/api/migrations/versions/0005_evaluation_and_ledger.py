"""Versioned evaluation and immutable balanced ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.add_column("runs", sa.Column("measured_tokens", sa.Integer()))
    op.add_column("runs", sa.Column("quality_score", sa.Integer()))
    op.add_column("runs", sa.Column("acceptance_deadline", sa.DateTime(timezone=True)))
    op.create_table(
        "metering_formula_versions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("version", sa.String(30), nullable=False, unique=True),
        sa.Column("definition_json", json_type, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "quality_rubric_versions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("schema_id", sa.String(100), nullable=False),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("definition_json", json_type, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_quality_rubric_schema_version",
        "quality_rubric_versions",
        ["schema_id", "version"],
        unique=True,
    )
    op.create_table(
        "quality_evaluations",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column(
            "rubric_version_id",
            sa.String(80),
            sa.ForeignKey("quality_rubric_versions.id"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("evaluation_mode", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=False),
        sa.Column("issues_json", json_type, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("response_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 100", name="quality_score"
        ),
    )
    op.create_index("ix_quality_evaluations_run_id", "quality_evaluations", ["run_id"])
    op.create_index(
        "uq_quality_evaluation_round",
        "quality_evaluations",
        ["run_id", "round_number"],
        unique=True,
    )
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("account_key", sa.String(120), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(40), sa.ForeignKey("users.id")),
        sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ledger_accounts_owner_id", "ledger_accounts", ["owner_id"])
    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("transaction_type", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("reference_type", sa.String(40), nullable=False),
        sa.Column("reference_id", sa.String(80), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ledger_transactions_reference_id", "ledger_transactions", ["reference_id"]
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.String(60),
            sa.ForeignKey("ledger_transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id", sa.String(60), sa.ForeignKey("ledger_accounts.id"), nullable=False
        ),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount <> 0", name="nonzero_amount"),
    )
    op.create_index("ix_ledger_entries_transaction_id", "ledger_entries", ["transaction_id"])
    op.create_index(
        "uq_ledger_entry_account",
        "ledger_entries",
        ["transaction_id", "account_id"],
        unique=True,
    )
    op.create_table(
        "daily_grant_claims",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column(
            "transaction_id",
            sa.String(60),
            sa.ForeignKey("ledger_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_grant_claims_user_id", "daily_grant_claims", ["user_id"])
    op.create_index(
        "uq_daily_grant", "daily_grant_claims", ["user_id", "claim_date"], unique=True
    )


def downgrade() -> None:
    op.drop_table("daily_grant_claims")
    op.drop_table("ledger_entries")
    op.drop_table("ledger_transactions")
    op.drop_table("ledger_accounts")
    op.drop_table("quality_evaluations")
    op.drop_table("quality_rubric_versions")
    op.drop_table("metering_formula_versions")
    op.drop_column("runs", "acceptance_deadline")
    op.drop_column("runs", "quality_score")
    op.drop_column("runs", "measured_tokens")
