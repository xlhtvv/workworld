from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from workworld_api.config import get_settings


def test_initial_migration_runs_on_clean_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database}")
    get_settings.cache_clear()
    configuration = Config("alembic.ini")
    command.upgrade(configuration, "head")
    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    tables = set(inspector.get_table_names())
    assert {
        "users",
        "email_verifications",
        "refresh_sessions",
        "schema_definitions",
        "schema_versions",
        "artifacts",
        "artifact_scan_results",
        "artifact_measurements",
        "agents",
        "agent_credentials",
        "agent_endpoints",
        "agent_connections",
        "agent_capacity_snapshots",
        "offerings",
        "offering_versions",
        "offering_certifications",
        "webhook_nonces",
        "tasks",
        "task_input_versions",
        "task_artifacts",
        "recommendations",
        "applications",
        "runs",
        "run_slot_reservations",
        "run_events",
        "clarification_requests",
        "budget_extension_requests",
        "rework_requests",
        "protocol_outbox",
        "metering_formula_versions",
        "token_policy_versions",
        "quality_rubric_versions",
        "quality_evaluations",
        "ledger_accounts",
        "ledger_transactions",
        "ledger_entries",
        "daily_grant_claims",
        "provider_profiles",
        "reviews",
        "review_replies",
        "moderation_results",
        "audit_events",
        "alembic_version",
    } <= tables
    assert "next_event_sequence" in {
        column["name"] for column in inspector.get_columns("runs")
    }
    command.check(configuration)
    command.downgrade(configuration, "0007")
    command.upgrade(configuration, "head")
    command.check(configuration)
    get_settings.cache_clear()
