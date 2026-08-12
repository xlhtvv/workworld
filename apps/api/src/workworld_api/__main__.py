import logging

import uvicorn
from alembic import command
from alembic.config import Config

from workworld_api.config import get_settings
from workworld_api.database import session_factory
from workworld_api.services.admin_bootstrap import ensure_bootstrap_admin
from workworld_api.services.evaluation import seed_evaluation_versions
from workworld_api.services.ledger import seed_token_policy
from workworld_api.services.s3_store import S3ArtifactStore
from workworld_api.services.schema_seed import seed_catalog


def bootstrap() -> None:
    settings = get_settings()
    command.upgrade(Config("alembic.ini"), "head")
    with session_factory()() as db:
        created = seed_catalog(db)
        logging.info("schema catalog ready created=%d", created)
        finance_created = seed_evaluation_versions(db)
        logging.info("evaluation versions ready created=%d", finance_created)
        policy_created = seed_token_policy(db)
        logging.info("token policy ready created=%d", policy_created)
        admin_created = ensure_bootstrap_admin(db, settings)
        logging.info("bootstrap admin ready created=%d", admin_created)
    S3ArtifactStore(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_bucket,
    ).ensure_bucket()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bootstrap()
    uvicorn.run("workworld_api.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
