"""Provider profiles, reviews, moderation, and audit history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "provider_profiles",
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "moderation_results",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(80), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("categories_json", json_type, nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("response_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_moderation_subject",
        "moderation_results",
        ["subject_type", "subject_id"],
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("reviewer_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("moderation_result_id", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="rating"),
    )
    op.create_index("ix_reviews_reviewer_id", "reviews", ["reviewer_id"])
    op.create_index("ix_reviews_provider_id", "reviews", ["provider_id"])
    op.create_table(
        "review_replies",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column(
            "review_id", sa.String(60), sa.ForeignKey("reviews.id"), nullable=False, unique=True
        ),
        sa.Column("provider_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("moderation_result_id", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(60)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(80), nullable=False),
        sa.Column("details_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("review_replies")
    op.drop_table("reviews")
    op.drop_table("moderation_results")
    op.drop_table("provider_profiles")
