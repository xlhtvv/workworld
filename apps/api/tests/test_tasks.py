from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentEndpoint,
    Offering,
    OfferingVersion,
)
from workworld_api.models import User
from workworld_api.services.auto_applications import AutoApplicationService
from workworld_api.services.ledger import LedgerService
from workworld_api.services.protocol import ProtocolService
from workworld_api.services.tasks import TaskError, TaskService
from workworld_api.task_models import Application, ProtocolOutbox, Recommendation, RunEvent, Task


def seed_market(db: Session, now: datetime) -> tuple[User, User, OfferingVersion]:
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
    agent = Agent(
        id="agent_1",
        owner_id=provider.id,
        name="Summary",
        slug="summary-agent",
        status="active",
        created_at=now,
    )
    endpoint = AgentEndpoint(
        id="endpoint_1",
        agent_id=agent.id,
        endpoint_type="pull",
        url=None,
        status="verified",
        resolved_addresses=[],
        verified_at=now,
        created_at=now,
    )
    offering = Offering(
        id="offering_1",
        agent_id=agent.id,
        owner_id=provider.id,
        slug="summary",
        status="published",
        latest_version_id="offering_1_v1",
        created_at=now,
    )
    version = OfferingVersion(
        id="offering_1_v1",
        offering_id=offering.id,
        version=1,
        schema_id="text.summarize",
        schema_version="1.0",
        name_i18n={"en": "Summary", "zh": "摘要"},
        description_i18n={"en": "Summary", "zh": "摘要"},
        capabilities=[],
        risk_disclosure="third party",
        output_license="publisher-use",
        sla_seconds=60,
        input_limits={"max_characters": 500000},
        estimated_tokens_min=1,
        estimated_tokens_max=10,
        estimated_seconds_min=1,
        estimated_seconds_max=10,
        auto_apply_policy={"enabled": True, "daily_limit": 1},
        status="published",
        content_sha256="0" * 64,
        created_at=now,
        published_at=now,
    )
    capacity = AgentCapacitySnapshot(
        id="capacity_1",
        agent_id=agent.id,
        status="online",
        max_concurrent_runs=1,
        active_runs=0,
        queue_capacity=0,
        estimated_wait_seconds=0,
        supported_offering_versions=[version.id],
        observed_at=now,
    )
    db.add_all([publisher, provider])
    db.flush()
    db.add(agent)
    db.flush()
    db.add_all([endpoint, offering, capacity])
    db.flush()
    db.add(version)
    db.commit()
    LedgerService(db).signup_grant(publisher)
    return publisher, provider, version


def create_open_task(service: TaskService, publisher: User, now: datetime, suffix: str = ""):
    return service.create(
        publisher,
        schema_id="text.summarize",
        schema_version="1.0",
        title=f"Summary {suffix}",
        public_summary="Summarize a public-safe document.",
        input_json={"text": "Private source", "difficulty": "simple"},
        field_visibility={"difficulty": "public"},
        difficulty="simple",
        acceptance_rules={"max_characters": 1000},
        budget_tokens=100,
        recruitment_deadline=now + timedelta(hours=1),
        completion_deadline=now + timedelta(days=1),
        assignment_mode="open_call",
        now=now,
    )


def test_open_call_is_sealed_and_selection_atomically_reserves_capacity() -> None:
    engine = create_engine("sqlite+pysqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        publisher, provider, version = seed_market(db, now)
        service = TaskService(db)
        task = create_open_task(service, publisher, now)
        application = service.apply(
            provider,
            task.id,
            version.id,
            estimated_tokens_min=5,
            estimated_tokens_max=9,
            estimated_completion_seconds=30,
            message="Sealed proposal",
            valid_until=now + timedelta(minutes=30),
            now=now,
        )
        run = service.select_application(publisher, task.id, application.id, now)
        assert run.state == "offer_sent"
        assert application.status == "selected"
        offer = db.query(RunEvent).filter_by(run_id=run.id, event_type="task.offer").one()
        assert offer.sequence == 1
        assert db.query(ProtocolOutbox).filter_by(run_event_id=offer.id).count() == 1

        second = create_open_task(service, publisher, now, "second")
        second_application = service.apply(
            provider,
            second.id,
            version.id,
            estimated_tokens_min=5,
            estimated_tokens_max=9,
            estimated_completion_seconds=30,
            message="Another",
            valid_until=now + timedelta(minutes=30),
            now=now,
        )
        with pytest.raises(TaskError, match="agent_capacity_unavailable"):
            service.select_application(publisher, second.id, second_application.id, now)


def test_task_schema_deadline_and_visibility_are_strict() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        publisher, _, version = seed_market(db, now)
        service = TaskService(db)
        with pytest.raises(TaskError, match="task_input_schema_invalid"):
            service.create(
                publisher,
                schema_id="text.summarize",
                schema_version="1.0",
                title="Bad",
                public_summary="Bad",
                input_json={"difficulty": "simple"},
                field_visibility={},
                difficulty="simple",
                acceptance_rules={},
                budget_tokens=1,
                recruitment_deadline=None,
                completion_deadline=now + timedelta(hours=1),
                assignment_mode="recommended",
                now=now,
            )
        with pytest.raises(TaskError, match="visibility_field_unknown"):
            service.create(
                publisher,
                schema_id="text.summarize",
                schema_version="1.0",
                title="Bad",
                public_summary="Bad",
                input_json={"text": "x", "difficulty": "simple"},
                field_visibility={"missing": "public"},
                difficulty="simple",
                acceptance_rules={},
                budget_tokens=1,
                recruitment_deadline=None,
                completion_deadline=now + timedelta(hours=1),
                assignment_mode="recommended",
                now=now,
            )
        recommended = service.create(
            publisher,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Good",
            public_summary="Good",
            input_json={"text": "x", "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={},
            budget_tokens=100,
            recruitment_deadline=None,
            completion_deadline=now + timedelta(hours=1),
            assignment_mode="recommended",
            now=now,
        )
        choices = db.query(Recommendation).filter_by(task_id=recommended.id).all()
        assert [choice.offering_version_id for choice in choices] == ["offering_1_v1"]

        first_run = service.select_recommended(publisher, recommended.id, version.id, now)
        ProtocolService(db).ingest_agent_message(
            "agent_1",
            {
                "run_id": first_run.id,
                "idempotency_key": "reject-first-offer",
                "sequence": 1,
                "type": "task.reject",
                "message_id": "00000000-0000-4000-8000-000000000001",
                "payload": {},
            },
        )
        second_run = service.select_recommended(publisher, recommended.id, version.id, now)
        assert second_run.attempt == 2
        assert second_run.id != first_run.id


def test_task_rejects_secrets_and_contact_exchange() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        publisher, _, _ = seed_market(db, now)
        service = TaskService(db)
        common = {
            "publisher": publisher,
            "schema_id": "text.summarize",
            "schema_version": "1.0",
            "title": "Safe title",
            "public_summary": "Safe summary",
            "field_visibility": {},
            "difficulty": "simple",
            "acceptance_rules": {},
            "budget_tokens": 100,
            "recruitment_deadline": None,
            "completion_deadline": now + timedelta(hours=1),
            "assignment_mode": "recommended",
            "now": now,
        }
        with pytest.raises(TaskError, match="task_input_contains_secret"):
            service.create(
                input_json={"text": "API key: sk-secret", "difficulty": "simple"},
                **common,
            )
        with pytest.raises(TaskError, match="content_blocked:contact_email"):
            service.create(
                input_json={"text": "Contact outside@example.com", "difficulty": "simple"},
                **common,
            )


def test_automatic_application_obeys_policy_and_daily_quota() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        publisher, _, _ = seed_market(db, now)
        task = create_open_task(TaskService(db), publisher, now)
        service = AutoApplicationService(db)
        assert service.apply_due(now) == 1
        assert service.apply_due(now) == 0
        application = db.query(Application).filter_by(task_id=task.id).one()
        assert application.status == "submitted"
        assert application.message == "Automatic sealed application"


def test_assignment_requires_clean_schema_input_artifacts() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        publisher = User(
            id="publisher",
            email="publisher@example.com",
            password_hash="x",
            role="user",
            email_verified=True,
            suspended=False,
            created_at=now,
        )
        task = Task(
            id="task_document",
            publisher_id=publisher.id,
            schema_id="document.summarize",
            schema_version="1.0",
            title="Document",
            public_summary="Document",
            input_json={"max_characters": 100, "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={},
            budget_tokens=100,
            completion_deadline=now + timedelta(hours=1),
            assignment_mode="recommended",
            status="matching",
            created_at=now,
        )
        db.add_all([publisher, task])
        db.commit()
        with pytest.raises(TaskError, match="task_input_artifact_count_invalid"):
            TaskService(db)._ensure_input_artifacts(task)
