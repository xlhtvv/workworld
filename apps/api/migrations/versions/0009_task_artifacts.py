"""Add the explicit, foreign-keyed Task-to-Artifact custody relation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_artifacts",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(40),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(40),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction IN ('input','output')", name="direction"),
        sa.CheckConstraint(
            "visibility IN ('public','applicants','winner')",
            name="visibility",
        ),
    )
    op.create_index(
        "uq_task_artifact", "task_artifacts", ["task_id", "artifact_id"], unique=True
    )
    op.create_index(
        "ix_task_artifacts_task_direction",
        "task_artifacts",
        ["task_id", "direction"],
    )
    op.execute(
        """
        INSERT INTO task_artifacts
            (id, task_id, artifact_id, direction, visibility, attached_at)
        SELECT
            'task_artifact_' || substr(artifact.id, 10),
            artifact.task_id,
            artifact.id,
            artifact.direction,
            'winner',
            artifact.created_at
        FROM artifacts AS artifact
        WHERE artifact.task_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("task_artifacts")
