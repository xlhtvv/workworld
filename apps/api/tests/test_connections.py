from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import Agent, AgentEndpoint
from workworld_api.models import User
from workworld_api.services.connections import ConnectionError, PullConnectionService


def test_reconnect_supersedes_old_generation_and_ack_is_monotonic() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.now(UTC)
        db.add(
            User(
                id="user_1",
                email="one@example.com",
                password_hash="x",
                role="user",
                email_verified=True,
                suspended=False,
                created_at=now,
            )
        )
        db.add(
            Agent(
                id="agent_1",
                owner_id="user_1",
                name="Pull",
                slug="pull",
                status="active",
                created_at=now,
            )
        )
        db.add(
            AgentEndpoint(
                id="endpoint_1",
                agent_id="agent_1",
                endpoint_type="pull",
                url=None,
                status="pending",
                resolved_addresses=[],
                created_at=now,
            )
        )
        db.commit()
        service = PullConnectionService(db)
        first = service.connect("agent_1")
        service.heartbeat(first.id, 7)
        second = service.connect("agent_1")
        db.refresh(first)
        assert first.disconnected_at is not None
        assert second.generation == 2
        assert second.acknowledged_sequence == 7
        with pytest.raises(ConnectionError, match="acknowledgement_regressed"):
            service.heartbeat(second.id, 6)
