"""Exercise winner-capacity and ledger-overspend races on real PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from workworld_api.database import session_factory
from workworld_api.ids import new_id
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentEndpoint,
    Offering,
    OfferingVersion,
)
from workworld_api.models import User
from workworld_api.services.ledger import LedgerService
from workworld_api.services.tasks import TaskError, TaskService
from workworld_api.task_models import RunSlotReservation


def seed_user(label: str) -> str:
    now = datetime.now(UTC)
    user_id = new_id("user")
    with session_factory()() as db:
        user = User(
            id=user_id,
            email=f"race-{label}-{uuid.uuid4().hex}@example.com",
            password_hash="not-used-by-internal-concurrency-smoke",
            role="user",
            email_verified=True,
            suspended=False,
            created_at=now,
        )
        db.add(user)
        db.commit()
        LedgerService(db).signup_grant(user)
    return user_id


def seed_offering(provider_id: str, label: str, capacity: int) -> tuple[str, str]:
    now = datetime.now(UTC)
    agent_id = new_id("agent")
    offering_id = new_id("offering")
    version_id = new_id("offering_version")
    with session_factory()() as db:
        db.add_all(
            [
                Agent(
                    id=agent_id,
                    owner_id=provider_id,
                    name=f"Race agent {label}",
                    slug=f"race-agent-{label}-{uuid.uuid4().hex}",
                    status="active",
                    created_at=now,
                ),
                AgentEndpoint(
                    id=new_id("endpoint"),
                    agent_id=agent_id,
                    endpoint_type="pull",
                    url=None,
                    status="verified",
                    resolved_addresses=[],
                    verified_at=now,
                    created_at=now,
                ),
                Offering(
                    id=offering_id,
                    agent_id=agent_id,
                    owner_id=provider_id,
                    slug=f"race-offering-{label}-{uuid.uuid4().hex}",
                    status="published",
                    latest_version_id=version_id,
                    created_at=now,
                ),
                OfferingVersion(
                    id=version_id,
                    offering_id=offering_id,
                    version=1,
                    schema_id="text.summarize",
                    schema_version="1.0",
                    name_i18n={"en": "Race summary", "zh": "并发摘要"},
                    description_i18n={"en": "Concurrency smoke", "zh": "并发冒烟测试"},
                    capabilities=[],
                    risk_disclosure="Test-only provider endpoint.",
                    output_license="publisher-use",
                    sla_seconds=60,
                    input_limits={"max_characters": 500_000},
                    estimated_tokens_min=1,
                    estimated_tokens_max=1,
                    estimated_seconds_min=1,
                    estimated_seconds_max=60,
                    auto_apply_policy={"enabled": False},
                    status="published",
                    content_sha256="0" * 64,
                    created_at=now,
                    published_at=now,
                ),
                AgentCapacitySnapshot(
                    id=new_id("capacity"),
                    agent_id=agent_id,
                    status="online",
                    max_concurrent_runs=capacity,
                    active_runs=0,
                    queue_capacity=capacity,
                    estimated_wait_seconds=0,
                    supported_offering_versions=[version_id],
                    observed_at=now,
                ),
            ]
        )
        db.commit()
    return agent_id, version_id


def create_task(publisher_id: str, budget: int, label: str) -> str:
    now = datetime.now(UTC)
    with session_factory()() as db:
        publisher = db.get(User, publisher_id)
        assert publisher is not None
        task = TaskService(db).create(
            publisher,
            schema_id="text.summarize",
            schema_version="1.0",
            title=f"Race task {label}",
            public_summary="Verify a real PostgreSQL transaction boundary.",
            input_json={"text": "A deterministic concurrency fixture.", "difficulty": "simple"},
            field_visibility={"difficulty": "public"},
            difficulty="simple",
            acceptance_rules={"max_characters": 1000},
            budget_tokens=budget,
            recruitment_deadline=None,
            completion_deadline=now + timedelta(days=1),
            assignment_mode="recommended",
            now=now,
        )
        return str(task.id)


def select_task(publisher_id: str, task_id: str, version_id: str) -> str:
    with session_factory()() as db:
        publisher = db.get(User, publisher_id)
        assert publisher is not None
        try:
            TaskService(db).select_recommended(publisher, task_id, version_id)
        except TaskError as exc:
            return f"rejected:{exc}"
        return "selected"


def capacity_race(provider_id: str) -> None:
    publisher_id = seed_user("capacity-publisher")
    agent_id, version_id = seed_offering(provider_id, "capacity", capacity=1)
    task_ids = [create_task(publisher_id, 10_000, f"capacity-{index}") for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(lambda task_id: select_task(publisher_id, task_id, version_id), task_ids)
        )
    assert outcomes.count("selected") == 1, outcomes
    assert any(item == "rejected:agent_capacity_unavailable" for item in outcomes), outcomes
    with session_factory()() as db:
        active = db.scalar(
            select(func.count(RunSlotReservation.id)).where(
                RunSlotReservation.agent_id == agent_id,
                RunSlotReservation.status == "active",
            )
        )
        assert active == 1, active


def overspend_race(provider_id: str) -> None:
    publisher_id = seed_user("ledger-publisher")
    _agent_id, version_id = seed_offering(provider_id, "ledger", capacity=2)
    task_ids = [create_task(publisher_id, 70_000, f"ledger-{index}") for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(lambda task_id: select_task(publisher_id, task_id, version_id), task_ids)
        )
    assert outcomes.count("selected") == 1, outcomes
    assert any(item == "rejected:insufficient_balance" for item in outcomes), outcomes
    with session_factory()() as db:
        balances = LedgerService(db).balances(publisher_id)
        assert balances["user_available"] == 30_000, balances
        assert balances["user_held"] == 70_000, balances


def main() -> None:
    provider_id = seed_user("provider")
    capacity_race(provider_id)
    overspend_race(provider_id)
    print("real PostgreSQL capacity and overspend races passed")


if __name__ == "__main__":
    main()
