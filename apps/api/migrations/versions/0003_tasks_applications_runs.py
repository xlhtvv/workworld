"""Tasks, sealed applications, Runs, and slot reservations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("publisher_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("schema_id", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("public_summary", sa.Text(), nullable=False),
        sa.Column("input_json", json_type, nullable=False),
        sa.Column("field_visibility", json_type, nullable=False),
        sa.Column("difficulty", sa.String(30), nullable=False),
        sa.Column("acceptance_rules", json_type, nullable=False),
        sa.Column("budget_tokens", sa.Integer(), nullable=False),
        sa.Column("recruitment_deadline", sa.DateTime(timezone=True)),
        sa.Column("completion_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assignment_mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "assignment_mode IN ('recommended','open_call')", name="assignment_mode"
        ),
        sa.CheckConstraint("budget_tokens > 0", name="positive_budget"),
    )
    op.create_index("ix_tasks_publisher_id", "tasks", ["publisher_id"])
    op.create_table(
        "task_input_versions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "task_id", sa.String(40), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_json", json_type, nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_input_versions_task_id", "task_input_versions", ["task_id"])
    op.create_index(
        "uq_task_input_version", "task_input_versions", ["task_id", "version"], unique=True
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "offering_version_id",
            sa.String(60),
            sa.ForeignKey("offering_versions.id"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("explanation_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recommendations_task_id", "recommendations", ["task_id"])
    op.create_index(
        "ix_recommendations_offering_version_id", "recommendations", ["offering_version_id"]
    )
    op.create_index(
        "uq_recommendation_candidate",
        "recommendations",
        ["task_id", "offering_version_id"],
        unique=True,
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "offering_version_id",
            sa.String(60),
            sa.ForeignKey("offering_versions.id"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("estimated_tokens_min", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens_max", sa.Integer(), nullable=False),
        sa.Column("estimated_completion_seconds", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("estimated_tokens_min >= 0", name="nonnegative_min_tokens"),
        sa.CheckConstraint("estimated_tokens_max >= estimated_tokens_min", name="token_range"),
    )
    op.create_index("ix_applications_task_id", "applications", ["task_id"])
    op.create_index("ix_applications_offering_version_id", "applications", ["offering_version_id"])
    op.create_index("ix_applications_provider_id", "applications", ["provider_id"])
    op.create_index(
        "uq_application_candidate",
        "applications",
        ["task_id", "offering_version_id"],
        unique=True,
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "offering_version_id",
            sa.String(60),
            sa.ForeignKey("offering_versions.id"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("protocol_version", sa.String(20), nullable=False),
        sa.Column("schema_version_id", sa.String(160), nullable=False),
        sa.Column("metering_formula_version_id", sa.String(80)),
        sa.Column("quality_rubric_version_id", sa.String(80)),
        sa.Column("last_agent_sequence", sa.Integer(), nullable=False),
        sa.Column("next_event_sequence", sa.Integer(), nullable=False),
        sa.Column("clarification_rounds", sa.Integer(), nullable=False),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runs_offering_version_id", "runs", ["offering_version_id"])
    op.create_index("ix_runs_agent_id", "runs", ["agent_id"])
    op.create_index("ix_runs_task_id", "runs", ["task_id"])
    op.create_index("uq_run_attempt", "runs", ["task_id", "attempt"], unique=True)
    op.create_table(
        "run_slot_reservations",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(40),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_active_agent_slots", "run_slot_reservations", ["agent_id", "status"])


def downgrade() -> None:
    op.drop_table("run_slot_reservations")
    op.drop_table("runs")
    op.drop_table("applications")
    op.drop_table("recommendations")
    op.drop_table("task_input_versions")
    op.drop_table("tasks")
