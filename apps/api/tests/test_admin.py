from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import Agent, Offering
from workworld_api.models import User
from workworld_api.reputation_models import AuditEvent
from workworld_api.routers.admin import (
    AdjustmentBody,
    adjustment,
    suspend_agent,
    suspend_offering,
    suspend_user,
)


def user(user_id: str, role: str = "user") -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        password_hash="x",
        role=role,
        email_verified=True,
        suspended=False,
        created_at=datetime.now(UTC),
    )


def test_admin_mutations_are_audited_and_ledger_adjustment_is_balanced() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = user("user_admin", "admin")
        target = user("user_target")
        agent = Agent(
            id="agent_admin_test",
            owner_id=target.id,
            name="Agent",
            slug="admin-test",
            status="active",
            created_at=datetime.now(UTC),
        )
        offering = Offering(
            id="offering_admin_test",
            agent_id=agent.id,
            owner_id=target.id,
            slug="admin-test",
            status="published",
            created_at=datetime.now(UTC),
        )
        db.add_all([admin, target, agent, offering])
        db.commit()

        assert suspend_user(target.id, admin, db)["suspended"] is True
        assert suspend_agent(agent.id, admin, db)["status"] == "suspended"
        assert suspend_offering(offering.id, admin, db)["status"] == "suspended"
        result = adjustment(
            AdjustmentBody(
                user_id=target.id,
                amount=250,
                idempotency_key="admin-test-adjustment",
                reason="Integration test credit",
            ),
            admin,
            db,
        )
        assert result["transaction_type"] == "admin_adjustment"
        events = db.query(AuditEvent).order_by(AuditEvent.created_at).all()
        assert [event.action for event in events] == [
            "user.suspended",
            "agent.suspended",
            "offering.suspended",
            "ledger.adjusted",
        ]
        ledger_event = events[-1]
        assert ledger_event.details_json["amount"] == 250
