"""Add provider-published, clean example Artifact references to Offering versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.add_column(
        "offering_versions",
        sa.Column(
            "example_artifact_ids",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    with op.batch_alter_table("offering_versions") as batch:
        batch.alter_column("example_artifact_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("offering_versions", "example_artifact_ids")
