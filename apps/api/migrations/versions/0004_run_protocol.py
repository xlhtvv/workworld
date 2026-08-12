"""Durable Run protocol events and structured requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "run_events",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(40),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("agent_sequence", sa.Integer()),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(50)),
        sa.Column("payload_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_index("uq_run_event_sequence", "run_events", ["run_id", "sequence"], unique=True)
    op.create_index(
        "uq_run_event_idempotency",
        "run_events",
        ["run_id", "idempotency_key"],
        unique=True,
    )
    op.create_table(
        "clarification_requests",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_schema", json_type, nullable=False),
        sa.Column("default_answer", json_type, nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_json", json_type),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_clarification_requests_run_id", "clarification_requests", ["run_id"])
    op.create_index(
        "uq_clarification_round",
        "clarification_requests",
        ["run_id", "round_number"],
        unique=True,
    )
    op.create_table(
        "budget_extension_requests",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("requested_tokens", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_budget_extension_requests_run_id", "budget_extension_requests", ["run_id"])
    op.create_table(
        "rework_requests",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False, unique=True
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("acceptance_rule_refs", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "protocol_outbox",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "run_event_id",
            sa.String(50),
            sa.ForeignKey("run_events.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_protocol_outbox_agent_id", "protocol_outbox", ["agent_id"])


def downgrade() -> None:
    op.drop_table("protocol_outbox")
    op.drop_table("rework_requests")
    op.drop_table("budget_extension_requests")
    op.drop_table("clarification_requests")
    op.drop_table("run_events")
