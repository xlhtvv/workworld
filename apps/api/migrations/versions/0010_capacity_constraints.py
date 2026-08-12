"""Align Agent capacity status and bounds with the protocol contract."""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_capacity_snapshots") as batch:
        batch.create_check_constraint(
            "status",
            "status IN ('online','offline','draining')",
        )
        batch.create_check_constraint(
            "active_within_max",
            "active_runs <= max_concurrent_runs",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_capacity_snapshots") as batch:
        batch.drop_constraint(
            "active_within_max", type_="check"
        )
        batch.drop_constraint("status", type_="check")
