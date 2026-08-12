"""Align initial Schema and Artifact constraints with ORM metadata.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("schema_versions") as batch:
        batch.drop_constraint(
            op.f("ck_schema_versions_ck_schema_versions_status"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_schema_versions_status"),
            "status IN ('draft','published','retired')",
        )
        batch.drop_constraint(
            op.f("uq_schema_versions_schema_version"), type_="unique"
        )
        batch.create_index(
            op.f("uq_schema_versions_schema_version"),
            ["schema_id", "version"],
            unique=True,
        )

    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint(
            op.f("ck_artifacts_ck_artifacts_nonnegative_size"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_artifacts_ck_artifacts_direction"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_artifacts_ck_artifacts_scan_status"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_artifacts_nonnegative_size"), "size_bytes >= 0"
        )
        batch.create_check_constraint(
            op.f("ck_artifacts_direction"), "direction IN ('input','output')"
        )
        batch.create_check_constraint(
            op.f("ck_artifacts_scan_status"),
            "scan_status IN ('pending','clean','infected','rejected','error')",
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint(op.f("ck_artifacts_nonnegative_size"), type_="check")
        batch.drop_constraint(op.f("ck_artifacts_direction"), type_="check")
        batch.drop_constraint(op.f("ck_artifacts_scan_status"), type_="check")
        batch.create_check_constraint(
            op.f("ck_artifacts_ck_artifacts_nonnegative_size"), "size_bytes >= 0"
        )
        batch.create_check_constraint(
            op.f("ck_artifacts_ck_artifacts_direction"),
            "direction IN ('input','output')",
        )
        batch.create_check_constraint(
            op.f("ck_artifacts_ck_artifacts_scan_status"),
            "scan_status IN ('pending','clean','infected','rejected','error')",
        )

    with op.batch_alter_table("schema_versions") as batch:
        batch.drop_index(op.f("uq_schema_versions_schema_version"))
        batch.create_unique_constraint(
            op.f("uq_schema_versions_schema_version"), ["schema_id", "version"]
        )
        batch.drop_constraint(op.f("ck_schema_versions_status"), type_="check")
        batch.create_check_constraint(
            op.f("ck_schema_versions_ck_schema_versions_status"),
            "status IN ('draft','published','retired')",
        )
