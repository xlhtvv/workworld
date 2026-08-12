import json
import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from workworld_api.domain.recommendation import Candidate, recommend
from workworld_api.ids import new_id
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentEndpoint,
    Offering,
    OfferingCertification,
    OfferingVersion,
)
from workworld_api.models import Artifact, ScanStatus, User
from workworld_api.schema_catalog import get_schema
from workworld_api.services.ledger import LedgerError, LedgerService
from workworld_api.services.moderation import ModerationBlocked, ModerationService
from workworld_api.task_models import (
    Application,
    ProtocolOutbox,
    Recommendation,
    Run,
    RunEvent,
    RunSlotReservation,
    Task,
    TaskInputVersion,
)


class TaskError(ValueError):
    pass


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        publisher: User,
        *,
        schema_id: str,
        schema_version: str,
        title: str,
        public_summary: str,
        input_json: dict[str, Any],
        field_visibility: dict[str, str],
        difficulty: str,
        acceptance_rules: dict[str, Any],
        budget_tokens: int,
        recruitment_deadline: datetime | None,
        completion_deadline: datetime,
        assignment_mode: str,
        now: datetime | None = None,
    ) -> Task:
        current = now or datetime.now(UTC)
        schema = get_schema(schema_id, schema_version)
        if schema is None:
            raise TaskError("schema_version_not_found")
        errors = list(Draft202012Validator(schema["input_schema"]).iter_errors(input_json))
        if errors:
            raise TaskError("task_input_schema_invalid")
        if difficulty not in schema["difficulty_multipliers"]:
            raise TaskError("difficulty_invalid")
        if budget_tokens <= 0:
            raise TaskError("budget_invalid")
        execution_seconds = (completion_deadline - current).total_seconds()
        if not 600 <= execution_seconds <= 30 * 86400:
            raise TaskError("completion_deadline_out_of_range")
        if assignment_mode == "open_call":
            if recruitment_deadline is None:
                raise TaskError("recruitment_deadline_required")
            recruitment_seconds = (recruitment_deadline - current).total_seconds()
            if not 600 <= recruitment_seconds <= 7 * 86400:
                raise TaskError("recruitment_deadline_out_of_range")
            if recruitment_deadline >= completion_deadline:
                raise TaskError("recruitment_after_completion")
        elif assignment_mode != "recommended":
            raise TaskError("assignment_mode_invalid")
        if not set(field_visibility).issubset(input_json):
            raise TaskError("visibility_field_unknown")
        if any(
            level not in {"public", "applicants", "winner"} for level in field_visibility.values()
        ):
            raise TaskError("visibility_level_invalid")
        task_id = new_id("task")
        serialized_input = json.dumps(input_json, ensure_ascii=False, sort_keys=True)
        if re.search(
            r"(?i)(?:api[_ -]?key|password|private[_ -]?key|-----BEGIN [A-Z ]+PRIVATE KEY-----)",
            serialized_input,
        ):
            raise TaskError("task_input_contains_secret")
        try:
            ModerationService(self.db).check_text(
                "task", task_id, f"{title}\n{public_summary}\n{serialized_input}"
            )
        except ModerationBlocked as exc:
            raise TaskError(str(exc)) from exc
        task = Task(
            id=task_id,
            publisher_id=publisher.id,
            schema_id=schema_id,
            schema_version=schema_version,
            title=title,
            public_summary=public_summary,
            input_json=input_json,
            field_visibility=field_visibility,
            difficulty=difficulty,
            acceptance_rules=acceptance_rules,
            budget_tokens=budget_tokens,
            recruitment_deadline=recruitment_deadline,
            completion_deadline=completion_deadline,
            assignment_mode=assignment_mode,
            status="open" if assignment_mode == "open_call" else "matching",
            created_at=current,
        )
        self.db.add(task)
        self.db.add(
            TaskInputVersion(
                id=f"{task.id}_input_v1",
                task_id=task.id,
                version=1,
                input_json=input_json,
                source="publisher",
                created_at=current,
            )
        )
        self.db.commit()
        if task.assignment_mode == "recommended":
            self.generate_recommendations(task, current)
        return task

    def generate_recommendations(
        self, task: Task, now: datetime | None = None
    ) -> list[Recommendation]:
        current = now or datetime.now(UTC)
        remaining_seconds = max(
            0, int((_aware(task.completion_deadline) - _aware(current)).total_seconds())
        )
        candidates: list[Candidate] = []
        versions = self.db.scalars(
            select(OfferingVersion).where(
                OfferingVersion.status == "published",
                OfferingVersion.schema_id == task.schema_id,
                OfferingVersion.schema_version == task.schema_version,
            )
        )
        for version in versions:
            offering = self.db.get(Offering, version.offering_id)
            if offering is None or offering.status != "published":
                continue
            capacity = self.db.scalar(
                select(AgentCapacitySnapshot)
                .where(AgentCapacitySnapshot.agent_id == offering.agent_id)
                .order_by(AgentCapacitySnapshot.observed_at.desc())
            )
            endpoint = self.db.scalar(
                select(AgentEndpoint).where(
                    AgentEndpoint.agent_id == offering.agent_id,
                    AgentEndpoint.status == "verified",
                )
            )
            active_slots = self.db.scalar(
                select(func.count(RunSlotReservation.id)).where(
                    RunSlotReservation.agent_id == offering.agent_id,
                    RunSlotReservation.status == "active",
                )
            )
            certification = self.db.scalar(
                select(OfferingCertification)
                .where(
                    OfferingCertification.offering_version_id == version.id,
                    OfferingCertification.status == "passed",
                )
                .order_by(OfferingCertification.completed_at.desc())
            )
            max_characters = version.input_limits.get("max_characters")
            within_limits = not isinstance(max_characters, int) or all(
                not isinstance(value, str) or len(value) <= max_characters
                for value in task.input_json.values()
            )
            max_runs = capacity.max_concurrent_runs if capacity else 0
            candidates.append(
                Candidate(
                    offering_version_id=version.id,
                    published=True,
                    schema_id=version.schema_id,
                    schema_version=version.schema_version,
                    input_within_limits=within_limits,
                    available=endpoint is not None
                    and capacity is not None
                    and capacity.status == "online",
                    capacity_available=(active_slots or 0) < max_runs,
                    estimated_tokens_max=version.estimated_tokens_max,
                    estimated_seconds_max=version.estimated_seconds_max,
                    quality_score=(certification.score or 0) / 100 if certification else 0,
                    reliability_score=1.0 if capacity and capacity.status == "online" else 0,
                    user_rating_score=0.5,
                )
            )
        ranked = recommend(
            candidates,
            schema_id=task.schema_id,
            schema_version=task.schema_version,
            budget_tokens=task.budget_tokens,
            completion_seconds=remaining_seconds,
        )
        records = [
            Recommendation(
                id=new_id("recommendation"),
                task_id=task.id,
                offering_version_id=item.offering_version_id,
                rank=index,
                score=round(item.score * 1_000_000),
                explanation_json=item.explanation,
                created_at=current,
            )
            for index, item in enumerate(ranked, start=1)
        ]
        self.db.add_all(records)
        self.db.commit()
        return records

    def apply(
        self,
        provider: User,
        task_id: str,
        offering_version_id: str,
        *,
        estimated_tokens_min: int,
        estimated_tokens_max: int,
        estimated_completion_seconds: int,
        message: str,
        valid_until: datetime,
        now: datetime | None = None,
    ) -> Application:
        current = now or datetime.now(UTC)
        task = self.db.get(Task, task_id)
        version = self.db.get(OfferingVersion, offering_version_id)
        offering = self.db.get(Offering, version.offering_id) if version else None
        if task is None or task.assignment_mode != "open_call" or task.status != "open":
            raise TaskError("task_not_open_for_applications")
        if task.recruitment_deadline is None or _expired(task.recruitment_deadline, current):
            raise TaskError("recruitment_closed")
        if (
            version is None
            or offering is None
            or version.status != "published"
            or offering.status != "published"
            or offering.owner_id != provider.id
            or version.schema_id != task.schema_id
            or version.schema_version != task.schema_version
        ):
            raise TaskError("offering_not_eligible")
        if not 0 <= estimated_tokens_min <= estimated_tokens_max <= task.budget_tokens:
            raise TaskError("application_token_range_invalid")
        if estimated_completion_seconds <= 0:
            raise TaskError("application_completion_invalid")
        if not _after(valid_until, current) or _after(valid_until, task.recruitment_deadline):
            raise TaskError("application_validity_invalid")
        application = Application(
            id=new_id("application"),
            task_id=task.id,
            offering_version_id=version.id,
            provider_id=provider.id,
            estimated_tokens_min=estimated_tokens_min,
            estimated_tokens_max=estimated_tokens_max,
            estimated_completion_seconds=estimated_completion_seconds,
            message=message,
            valid_until=valid_until,
            status="submitted",
            created_at=current,
        )
        try:
            ModerationService(self.db).check_text(
                "application", application.id, application.message
            )
        except ModerationBlocked as exc:
            raise TaskError(str(exc)) from exc
        self.db.add(application)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise TaskError("duplicate_application") from exc
        return application

    def select_application(
        self, publisher: User, task_id: str, application_id: str, now: datetime | None = None
    ) -> Run:
        current = now or datetime.now(UTC)
        task = self.db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        application = self.db.get(Application, application_id)
        if (
            task is None
            or task.publisher_id != publisher.id
            or task.status != "open"
            or application is None
            or application.task_id != task.id
            or application.status != "submitted"
            or _expired(application.valid_until, current)
        ):
            raise TaskError("application_not_selectable")
        return self._assign(task, application.offering_version_id, application, current)

    def select_recommended(
        self, publisher: User, task_id: str, offering_version_id: str, now: datetime | None = None
    ) -> Run:
        current = now or datetime.now(UTC)
        task = self.db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if (
            task is None
            or task.publisher_id != publisher.id
            or task.assignment_mode != "recommended"
            or task.status != "matching"
        ):
            raise TaskError("task_not_selectable")
        recommendation = self.db.scalar(
            select(Recommendation).where(
                Recommendation.task_id == task.id,
                Recommendation.offering_version_id == offering_version_id,
            )
        )
        if recommendation is None:
            raise TaskError("offering_not_recommended")
        return self._assign(task, offering_version_id, None, current)

    def _assign(
        self,
        task: Task,
        offering_version_id: str,
        selected_application: Application | None,
        now: datetime,
    ) -> Run:
        self._ensure_input_artifacts(task)
        version = self.db.get(OfferingVersion, offering_version_id)
        offering = self.db.get(Offering, version.offering_id) if version else None
        if (
            version is None
            or offering is None
            or version.status != "published"
            or offering.status != "published"
            or version.schema_id != task.schema_id
            or version.schema_version != task.schema_version
            or version.estimated_tokens_max > task.budget_tokens
        ):
            raise TaskError("offering_not_eligible")
        agent = self.db.scalar(select(Agent).where(Agent.id == offering.agent_id).with_for_update())
        if agent is None or agent.status != "active":
            raise TaskError("agent_unavailable")
        endpoint = self.db.scalar(
            select(AgentEndpoint).where(
                AgentEndpoint.agent_id == agent.id, AgentEndpoint.status == "verified"
            )
        )
        capacity = self.db.scalar(
            select(AgentCapacitySnapshot)
            .where(
                AgentCapacitySnapshot.agent_id == agent.id,
                AgentCapacitySnapshot.status == "online",
            )
            .order_by(AgentCapacitySnapshot.observed_at.desc())
        )
        active_slots = self.db.scalar(
            select(func.count(RunSlotReservation.id)).where(
                RunSlotReservation.agent_id == agent.id,
                RunSlotReservation.status == "active",
            )
        )
        if (
            endpoint is None
            or capacity is None
            or (active_slots or 0) >= capacity.max_concurrent_runs
        ):
            raise TaskError("agent_capacity_unavailable")
        try:
            LedgerService(self.db).hold(task.publisher_id, task.id, task.budget_tokens)
        except LedgerError as exc:
            self.db.rollback()
            raise TaskError(str(exc)) from exc
        run = Run(
            id=new_id("run"),
            task_id=task.id,
            attempt=(
                self.db.scalar(select(func.max(Run.attempt)).where(Run.task_id == task.id)) or 0
            )
            + 1,
            offering_version_id=version.id,
            agent_id=agent.id,
            state="offer_sent",
            protocol_version="1.0",
            schema_version_id=f"{task.schema_id}@{task.schema_version}",
            last_agent_sequence=0,
            next_event_sequence=2,
            clarification_rounds=0,
            rework_count=0,
            offer_expires_at=now + timedelta(minutes=10),
            completion_deadline=task.completion_deadline,
            created_at=now,
        )
        self.db.add(run)
        self.db.flush()
        offer_event = RunEvent(
            id=new_id("event"),
            run_id=run.id,
            sequence=1,
            agent_sequence=None,
            message_id=str(uuid.uuid4()),
            idempotency_key=f"offer:{run.id}:attempt:{run.attempt}",
            event_type="task.offer",
            actor_type="system",
            actor_id=None,
            payload_json={
                "task_id": task.id,
                "schema_version_id": run.schema_version_id,
                "completion_deadline": task.completion_deadline.isoformat(),
                "budget_tokens": task.budget_tokens,
                "input": task.input_json,
                "input_artifact_ids": list(
                    self.db.scalars(
                        select(Artifact.id).where(
                            Artifact.task_id == task.id,
                            Artifact.direction == "input",
                            Artifact.scan_status == ScanStatus.CLEAN,
                            Artifact.deleted_at.is_(None),
                        )
                    )
                ),
                "acceptance_rules": task.acceptance_rules,
            },
            created_at=now,
        )
        self.db.add(offer_event)
        self.db.flush()
        self.db.add(
            ProtocolOutbox(
                id=new_id("outbox"),
                run_event_id=offer_event.id,
                agent_id=agent.id,
                status="pending",
                attempts=0,
                available_at=now,
            )
        )
        self.db.add(
            RunSlotReservation(
                id=new_id("slot"),
                run_id=run.id,
                agent_id=agent.id,
                status="active",
                reserved_at=now,
            )
        )
        task.status = "candidate_selected"
        if selected_application is not None:
            selected_application.status = "selected"
            for other in self.db.scalars(
                select(Application).where(
                    Application.task_id == task.id, Application.id != selected_application.id
                )
            ):
                other.status = "not_selected"
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise TaskError("task_already_assigned") from exc
        return run

    def _ensure_input_artifacts(self, task: Task) -> None:
        schema = get_schema(task.schema_id, task.schema_version)
        if schema is None:
            raise TaskError("schema_version_not_found")
        artifacts = list(
            self.db.scalars(
                select(Artifact).where(
                    Artifact.task_id == task.id,
                    Artifact.direction == "input",
                    Artifact.scan_status == ScanStatus.CLEAN,
                    Artifact.deleted_at.is_(None),
                )
            )
        )
        counts = Counter(row.kind for row in artifacts)
        for requirement in schema["artifacts"]["input"]:
            count = counts[str(requirement["kind"])]
            if not int(requirement["min"]) <= count <= int(requirement["max"]):
                raise TaskError("task_input_artifact_count_invalid")


def _expired(value: datetime, now: datetime) -> bool:
    comparable_now = now if value.tzinfo is not None else now.replace(tzinfo=None)
    return value < comparable_now


def _after(left: datetime, right: datetime) -> bool:
    comparable_left = left
    if left.tzinfo is not None and right.tzinfo is None:
        comparable_left = left.replace(tzinfo=None)
    elif left.tzinfo is None and right.tzinfo is not None:
        comparable_left = left.replace(tzinfo=right.tzinfo)
    return comparable_left > right


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
