from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.market_models import Agent, AgentEndpoint
from workworld_api.models import User
from workworld_api.services.endpoint_security import UnsafeEndpoint, ValidatedEndpoint
from workworld_api.services.push_delivery import PushDeliveryService


def test_push_health_revalidates_addresses_and_throttles_attempts() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all(
            [
                User(
                    id="user_1",
                    email="provider@example.com",
                    password_hash="x",
                    role="user",
                    email_verified=True,
                    suspended=False,
                    created_at=now,
                ),
                Agent(
                    id="agent_1",
                    owner_id="user_1",
                    name="Push",
                    slug="push",
                    status="active",
                    created_at=now,
                ),
                AgentEndpoint(
                    id="endpoint_1",
                    agent_id="agent_1",
                    endpoint_type="push",
                    url="https://provider.example/workworld",
                    status="verified",
                    resolved_addresses=["8.8.8.8"],
                    verified_at=now,
                    created_at=now,
                ),
            ]
        )
        db.commit()
        challenges: list[str] = []
        validated = ValidatedEndpoint(
            "https://provider.example/workworld",
            "provider.example",
            443,
            frozenset({"1.1.1.1"}),
        )
        service = PushDeliveryService(
            db,
            Settings(push_health_interval_seconds=60),
            health_verifier=lambda _endpoint, challenge: challenges.append(challenge),
            endpoint_validator=lambda _url: validated,
        )
        assert service.check_health(now) == (1, 0)
        assert service.check_health(now + timedelta(seconds=30)) == (0, 0)
        endpoint = db.get(AgentEndpoint, "endpoint_1")
        assert endpoint is not None and endpoint.resolved_addresses == ["1.1.1.1"]
        assert len(challenges) == 1 and len(challenges[0]) > 20

        service.endpoint_validator = lambda _url: (_ for _ in ()).throw(
            UnsafeEndpoint("endpoint_dns_failed")
        )
        assert service.check_health(now + timedelta(seconds=61)) == (0, 1)
        assert endpoint.status == "verified"
