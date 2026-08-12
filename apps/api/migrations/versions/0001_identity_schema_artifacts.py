"""Identity, schema catalog, and Artifact custody tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "users",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("suspended", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "schema_definitions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "schema_versions",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column(
            "schema_id", sa.String(100), sa.ForeignKey("schema_definitions.id"), nullable=False
        ),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("definition_json", json_type, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('draft','published','retired')", name="ck_schema_versions_status"
        ),
        sa.UniqueConstraint("schema_id", "version", name="uq_schema_versions_schema_version"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_id", sa.String(40)),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("declared_mime_type", sa.String(255), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(1000), unique=True),
        sa.Column("multipart_upload_id", sa.String(1000)),
        sa.Column("scan_status", sa.String(20), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("delete_after", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifacts_nonnegative_size"),
        sa.CheckConstraint("direction IN ('input','output')", name="ck_artifacts_direction"),
        sa.CheckConstraint(
            "scan_status IN ('pending','clean','infected','rejected','error')",
            name="ck_artifacts_scan_status",
        ),
    )
    op.create_index("ix_artifacts_owner_id", "artifacts", ["owner_id"])
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"])
    op.create_index("ix_artifacts_task_direction", "artifacts", ["task_id", "direction"])
    op.create_table(
        "artifact_scan_results",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(40),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scanner", sa.String(100), nullable=False),
        sa.Column("scanner_version", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("signature", sa.String(500)),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_artifact_scan_results_artifact_id", "artifact_scan_results", ["artifact_id"]
    )
    op.create_table(
        "artifact_measurements",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.String(40),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_version", sa.String(50), nullable=False),
        sa.Column("values_json", json_type, nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_artifact_measurements_artifact_id", "artifact_measurements", ["artifact_id"]
    )


def downgrade() -> None:
    op.drop_table("artifact_measurements")
    op.drop_table("artifact_scan_results")
    op.drop_table("artifacts")
    op.drop_table("schema_versions")
    op.drop_table("schema_definitions")
    op.drop_table("refresh_sessions")
    op.drop_table("email_verifications")
    op.drop_table("users")
