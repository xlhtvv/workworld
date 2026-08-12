"""Agents, endpoints, capacity, Offerings, and certification."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "agents",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','suspended')", name="status"),
    )
    op.create_index("ix_agents_owner_id", "agents", ["owner_id"])
    op.create_index("uq_agents_owner_slug", "agents", ["owner_id", "slug"], unique=True)
    op.create_table(
        "agent_credentials",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(40),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_prefix", sa.String(24), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_credentials_agent_id", "agent_credentials", ["agent_id"])
    op.create_table(
        "agent_endpoints",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(40),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint_type", sa.String(10), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_addresses", json_type, nullable=False),
        sa.Column("challenge_hash", sa.String(64)),
        sa.Column("challenge_expires_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("endpoint_type IN ('pull','push')", name="endpoint_type"),
        sa.CheckConstraint("status IN ('pending','verified','failed','revoked')", name="status"),
    )
    op.create_index("ix_agent_endpoints_agent_id", "agent_endpoints", ["agent_id"])
    op.create_table(
        "agent_connections",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_sequence", sa.Integer(), nullable=False),
    )
    op.create_index("ix_agent_connections_agent_id", "agent_connections", ["agent_id"])
    op.create_index(
        "uq_agent_connection_generation",
        "agent_connections",
        ["agent_id", "generation"],
        unique=True,
    )
    op.create_table(
        "agent_capacity_snapshots",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=False),
        sa.Column("active_runs", sa.Integer(), nullable=False),
        sa.Column("queue_capacity", sa.Integer(), nullable=False),
        sa.Column("estimated_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("supported_offering_versions", json_type, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("max_concurrent_runs >= 0", name="nonnegative_max_runs"),
        sa.CheckConstraint("active_runs >= 0", name="nonnegative_active_runs"),
        sa.CheckConstraint("queue_capacity >= 0", name="nonnegative_queue"),
        sa.CheckConstraint("estimated_wait_seconds >= 0", name="nonnegative_wait"),
    )
    op.create_index(
        "ix_agent_capacity_snapshots_agent_id", "agent_capacity_snapshots", ["agent_id"]
    )
    op.create_table(
        "offerings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("owner_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("latest_version_id", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_offerings_agent_id", "offerings", ["agent_id"])
    op.create_index("ix_offerings_owner_id", "offerings", ["owner_id"])
    op.create_index("uq_offerings_owner_slug", "offerings", ["owner_id", "slug"], unique=True)
    op.create_table(
        "offering_versions",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column(
            "offering_id",
            sa.String(40),
            sa.ForeignKey("offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_id", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("name_i18n", json_type, nullable=False),
        sa.Column("description_i18n", json_type, nullable=False),
        sa.Column("capabilities", json_type, nullable=False),
        sa.Column("risk_disclosure", sa.Text(), nullable=False),
        sa.Column("output_license", sa.String(200), nullable=False),
        sa.Column("sla_seconds", sa.Integer(), nullable=False),
        sa.Column("input_limits", json_type, nullable=False),
        sa.Column("estimated_tokens_min", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens_max", sa.Integer(), nullable=False),
        sa.Column("estimated_seconds_min", sa.Integer(), nullable=False),
        sa.Column("estimated_seconds_max", sa.Integer(), nullable=False),
        sa.Column("auto_apply_policy", json_type, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("estimated_tokens_min >= 0", name="nonnegative_min_tokens"),
        sa.CheckConstraint("estimated_tokens_max >= estimated_tokens_min", name="token_range"),
    )
    op.create_index("ix_offering_versions_offering_id", "offering_versions", ["offering_id"])
    op.create_index(
        "uq_offering_versions_number",
        "offering_versions",
        ["offering_id", "version"],
        unique=True,
    )
    op.create_table(
        "offering_certifications",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "offering_version_id",
            sa.String(60),
            sa.ForeignKey("offering_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_suite_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("level", sa.String(30), nullable=False),
        sa.Column("checks_json", json_type, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64)),
        sa.Column("score", sa.Integer()),
        sa.Column("log_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_offering_certifications_offering_version_id",
        "offering_certifications",
        ["offering_version_id"],
    )
    op.create_table(
        "webhook_nonces",
        sa.Column("nonce", sa.String(128), primary_key=True),
        sa.Column("agent_id", sa.String(40), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_nonces_agent_id", "webhook_nonces", ["agent_id"])


def downgrade() -> None:
    op.drop_table("webhook_nonces")
    op.drop_table("offering_certifications")
    op.drop_table("offering_versions")
    op.drop_table("offerings")
    op.drop_table("agent_capacity_snapshots")
    op.drop_table("agent_connections")
    op.drop_table("agent_endpoints")
    op.drop_table("agent_credentials")
    op.drop_table("agents")
