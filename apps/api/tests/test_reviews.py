from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import Agent
from workworld_api.models import User
from workworld_api.reputation_models import ModerationResult
from workworld_api.services.reviews import ReviewError, ReviewService
from workworld_api.task_models import Run, Task


def seed_completed_run(db: Session) -> tuple[User, User, User, Run]:
    now = datetime.now(UTC)
    publisher = User(
        id="user_publisher",
        email="publisher@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=now,
    )
    provider = User(
        id="user_provider",
        email="provider@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=now,
    )
    stranger = User(
        id="user_stranger",
        email="stranger@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=now,
    )
    agent = Agent(
        id="agent_1",
        owner_id=provider.id,
        name="Agent",
        slug="agent",
        status="active",
        created_at=now,
    )
    task = Task(
        id="task_1",
        publisher_id=publisher.id,
        schema_id="text.summarize",
        schema_version="1.0",
        title="Task",
        public_summary="Task",
        input_json={"text": "source", "difficulty": "simple"},
        field_visibility={},
        difficulty="simple",
        acceptance_rules={},
        budget_tokens=100,
        completion_deadline=now,
        assignment_mode="recommended",
        status="completed",
        created_at=now,
    )
    run = Run(
        id="run_1",
        task_id=task.id,
        attempt=1,
        offering_version_id="offering_version_1",
        agent_id=agent.id,
        state="completed",
        protocol_version="1.0",
        schema_version_id="text.summarize@1.0",
        last_agent_sequence=0,
        next_event_sequence=1,
        clarification_rounds=0,
        rework_count=0,
        offer_expires_at=now,
        completion_deadline=now,
        completed_at=now,
        created_at=now,
    )
    db.add_all([publisher, provider, stranger, agent, task, run])
    db.commit()
    return publisher, provider, stranger, run


def test_verified_review_is_unique_and_provider_can_reply() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        publisher, provider, stranger, run = seed_completed_run(db)
        service = ReviewService(db)
        review = service.create(publisher, run.id, 5, "Reliable and clear delivery.")
        assert review.status == "visible"
        with pytest.raises(ReviewError, match="review_already_exists"):
            service.create(publisher, run.id, 4, "Second review")
        with pytest.raises(ReviewError, match="review_not_found"):
            service.reply(stranger, review.id, "Not mine")
        reply = service.reply(provider, review.id, "Thank you for the feedback.")
        assert reply.status == "visible"
        summary = service.provider_summary(provider.id)
        assert summary["completed_runs"] == 1
        assert summary["average_rating"] == 5


def test_contact_and_external_payment_guidance_is_blocked_and_audited() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        publisher, _, _, run = seed_completed_run(db)
        with pytest.raises(ReviewError, match="content_blocked:contact_email,external_payment"):
            ReviewService(db).create(
                publisher,
                run.id,
                5,
                "Pay me by PayPal and email me at outside@example.com",
            )
        result = db.query(ModerationResult).one()
        assert result.blocked is True
        assert set(result.categories_json) == {"contact_email", "external_payment"}


def test_public_provider_profile_resolves_agent_slug_and_includes_verified_review() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        publisher, provider, _, run = seed_completed_run(db)
        service = ReviewService(db)
        service.upsert_profile(provider, "Reliable Provider", "Provider-hosted text services.")
        review = service.create(publisher, run.id, 5, "Strong result.")
        service.reply(provider, review.id, "Thank you.")
        profile = service.public_profile("agent")
        assert profile["provider_id"] == provider.id
        assert profile["display_name"] == "Reliable Provider"
        assert profile["reviews"] == [
            {
                "id": review.id,
                "rating": 5,
                "body": "Strong result.",
                "created_at": review.created_at,
                "reply": "Thank you.",
            }
        ]


def test_provider_profile_is_moderated() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _, provider, _, _ = seed_completed_run(db)
        with pytest.raises(ReviewError, match="content_blocked:contact_email"):
            ReviewService(db).upsert_profile(
                provider, "Outside contact", "Email provider@example.com"
            )
