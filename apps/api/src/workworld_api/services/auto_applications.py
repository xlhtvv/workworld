from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    Offering,
    OfferingVersion,
)
from workworld_api.models import User
from workworld_api.services.tasks import TaskError, TaskService
from workworld_api.task_models import Application, Task


class AutoApplicationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def apply_due(self, now: datetime | None = None, limit: int = 100) -> int:
        current = now or datetime.now(UTC)
        tasks = list(
            self.db.scalars(
                select(Task)
                .where(
                    Task.assignment_mode == "open_call",
                    Task.status == "open",
                    Task.recruitment_deadline > current,
                )
                .limit(limit)
            )
        )
        created = 0
        for task in tasks:
            versions = self.db.scalars(
                select(OfferingVersion).where(
                    OfferingVersion.status == "published",
                    OfferingVersion.schema_id == task.schema_id,
                    OfferingVersion.schema_version == task.schema_version,
                )
            )
            for version in versions:
                if not self._eligible(task, version, current):
                    continue
                offering = self.db.get(Offering, version.offering_id)
                provider = self.db.get(User, offering.owner_id) if offering else None
                if offering is None or provider is None:
                    continue
                recruitment_deadline = task.recruitment_deadline
                if recruitment_deadline is None:
                    continue
                policy = version.auto_apply_policy
                try:
                    TaskService(self.db).apply(
                        provider,
                        task.id,
                        version.id,
                        estimated_tokens_min=version.estimated_tokens_min,
                        estimated_tokens_max=version.estimated_tokens_max,
                        estimated_completion_seconds=version.estimated_seconds_max,
                        message=str(policy.get("message", "Automatic sealed application")),
                        valid_until=min(
                            _aware(recruitment_deadline),
                            current + timedelta(hours=int(policy.get("valid_hours", 24))),
                        ),
                        now=current,
                    )
                except TaskError:
                    self.db.rollback()
                    continue
                created += 1
        return created

    def _eligible(self, task: Task, version: OfferingVersion, now: datetime) -> bool:
        policy = version.auto_apply_policy
        if not bool(policy.get("enabled", False)):
            return False
        if version.estimated_tokens_max > min(
            task.budget_tokens, int(policy.get("max_budget_tokens", task.budget_tokens))
        ):
            return False
        if version.estimated_seconds_max > int(
            policy.get("max_completion_seconds", 30 * 86400)
        ):
            return False
        offering = self.db.get(Offering, version.offering_id)
        agent = self.db.get(Agent, offering.agent_id) if offering else None
        if offering is None or agent is None or offering.status != "published":
            return False
        capacity = self.db.scalar(
            select(AgentCapacitySnapshot)
            .where(
                AgentCapacitySnapshot.agent_id == agent.id,
                AgentCapacitySnapshot.status == "online",
            )
            .order_by(AgentCapacitySnapshot.observed_at.desc())
            .limit(1)
        )
        if capacity is None or version.id not in capacity.supported_offering_versions:
            return False
        start = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        daily = self.db.scalar(
            select(func.count(Application.id)).where(
                Application.offering_version_id == version.id,
                Application.created_at >= start,
            )
        ) or 0
        return daily < int(policy.get("daily_limit", 10))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
