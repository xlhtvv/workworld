import logging
import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path

from workworld_api.config import get_settings
from workworld_api.database import session_factory
from workworld_api.services.acceptance import AcceptanceService
from workworld_api.services.artifact_retention import ArtifactRetentionService
from workworld_api.services.auto_applications import AutoApplicationService
from workworld_api.services.evaluation import EvaluationService
from workworld_api.services.push_delivery import PushDeliveryService
from workworld_api.services.run_control import RunControlService
from workworld_api.services.s3_store import S3ArtifactStore

WORKER_HEALTH_PATH = Path(
    os.environ.get("WORKWORLD_WORKER_HEALTH_PATH", "/tmp/workworld-worker-health")
)


def run_maintenance() -> tuple[int, int, int, int, int, int, int, int, int, int, int, int]:
    with session_factory()() as db:
        settings = get_settings()
        service = RunControlService(db)
        clarifications = service.default_expired_clarifications()
        deadlines = service.sweep_deadlines()
        unreachable = service.mark_unreachable_agents()
        push = PushDeliveryService(db, settings)
        healthy_endpoints, health_failures = push.check_health()
        delivered, delivery_failures = push.dispatch_due()
        evaluations = EvaluationService(db, settings).evaluate_pending()
        auto_acceptances = AcceptanceService(db).auto_accept_due()
        terminal_settlements = AcceptanceService(db).settle_terminal_runs()
        applications = AutoApplicationService(db).apply_due()
        expired_artifacts = ArtifactRetentionService(
            db,
            S3ArtifactStore(
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            ),
        ).expire_due(datetime.now(UTC))
        return (
            clarifications,
            deadlines,
            unreachable,
            healthy_endpoints,
            health_failures,
            delivered,
            delivery_failures,
            evaluations,
            auto_acceptances,
            terminal_settlements,
            applications,
            expired_artifacts,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    logging.info("workworld worker ready")
    while not stopped.wait(5):
        try:
            (
                clarifications,
                deadlines,
                unreachable,
                healthy_endpoints,
                health_failures,
                delivered,
                delivery_failures,
                evaluations,
                auto_acceptances,
                terminal_settlements,
                applications,
                expired_artifacts,
            ) = run_maintenance()
            WORKER_HEALTH_PATH.touch()
            if any(
                [
                    clarifications,
                    deadlines,
                    unreachable,
                    healthy_endpoints,
                    health_failures,
                    delivered,
                    delivery_failures,
                    evaluations,
                    auto_acceptances,
                    terminal_settlements,
                    applications,
                    expired_artifacts,
                ]
            ):
                logging.info(
                    "maintenance clarifications=%d deadlines=%d unreachable=%d "
                    "healthy_endpoints=%d health_failures=%d "
                    "delivered=%d delivery_failures=%d evaluations=%d "
                    "auto_acceptances=%d terminal_settlements=%d applications=%d "
                    "expired_artifacts=%d",
                    clarifications,
                    deadlines,
                    unreachable,
                    healthy_endpoints,
                    health_failures,
                    delivered,
                    delivery_failures,
                    evaluations,
                    auto_acceptances,
                    terminal_settlements,
                    applications,
                    expired_artifacts,
                )
        except Exception:
            logging.exception("maintenance iteration failed")


if __name__ == "__main__":
    main()
