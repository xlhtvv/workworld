"""Start a clean, migrated API for host-level Playwright journeys.

This intentionally uses the real ASGI app, SQLAlchemy services, Alembic migrations,
and an on-disk SQLite database. Service-dependent artifact journeys remain in the
Compose E2E suite because MinIO and ClamAV must not be replaced here.
"""

from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from workworld_api.config import get_settings
from workworld_api.database import session_factory
from workworld_api.services.admin_bootstrap import ensure_bootstrap_admin
from workworld_api.services.evaluation import seed_evaluation_versions
from workworld_api.services.ledger import seed_token_policy
from workworld_api.services.schema_seed import seed_catalog

TEST_DATABASE = Path("/tmp/workworld-playwright.db")
TEST_DATABASE_URL = f"sqlite+pysqlite:///{TEST_DATABASE}"


def prepare_database() -> None:
    settings = get_settings()
    if settings.environment != "test" or settings.database_url != TEST_DATABASE_URL:
        raise RuntimeError("browser test API requires the fixed test SQLite database")
    TEST_DATABASE.unlink(missing_ok=True)
    command.upgrade(Config("alembic.ini"), "head")
    with session_factory()() as db:
        seed_catalog(db)
        seed_evaluation_versions(db)
        seed_token_policy(db)
        ensure_bootstrap_admin(db, settings)


if __name__ == "__main__":
    prepare_database()
    uvicorn.run("workworld_api.main:app", host="127.0.0.1", port=8000)
