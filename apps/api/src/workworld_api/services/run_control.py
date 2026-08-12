import json
from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workworld_api.domain.run_state import RunState
from workworld_api.market_models import Agent, AgentConnection, AgentEndpoint
from workworld_api.models import User
from workworld_api.services.ledger import LedgerError, LedgerService
from workworld_api.services.moderation import ModerationBlocked, ModerationService
from workworld_api.services.protocol import ProtocolService
from workworld_api.task_models import (
    BudgetExtensionRequest,
    ClarificationRequest,
    Run,
    RunEvent,
    Task,
    TaskInputVersion,
)


class RunControlError(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class RunControlService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def visible_run(self, user: User, run_id: str, *, lock: bool = False) -> tuple[Run, Task]:
        query = select(Run).where(Run.id == run_id)
        run = self.db.scalar(query.with_for_update() if lock else query)
        if run is None:
            raise RunControlError("run_not_found")
        task = self.db.get(Task, run.task_id)
        agent = self.db.get(Agent, run.agent_id)
        if task is None or agent is None or user.id not in {task.publisher_id, agent.owner_id}:
            raise RunControlError("run_not_found")
        return run, task

    def events(self, user: User, run_id: str, after: int = 0) -> list[RunEvent]:
        self.visible_run(user, run_id)
        return list(
            self.db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
                .order_by(RunEvent.sequence)
            )
        )

    def answer_clarification(
        self,
        publisher: User,
        run_id: str,
        clarification_id: str,
        answer: dict[str, Any],
        *,
        use_default: bool = False,
    ) -> RunEvent:
        run, task = self.visible_run(publisher, run_id, lock=True)
        if task.publisher_id != publisher.id:
            raise RunControlError("publisher_required")
        request = self.db.scalar(
            select(ClarificationRequest)
            .where(
                ClarificationRequest.id == clarification_id,
                ClarificationRequest.run_id == run.id,
            )
            .with_for_update()
        )
        if request is None or request.status != "pending":
            raise RunControlError("clarification_not_pending")
        resolved = request.default_answer if use_default else answer
        if list(Draft202012Validator(request.answer_schema).iter_errors(resolved)):
            raise RunControlError("clarification_answer_invalid")
        try:
            ModerationService(self.db).check_text(
                "clarification_answer",
                request.id,
                json.dumps(resolved, ensure_ascii=False, sort_keys=True),
            )
        except ModerationBlocked as exc:
            raise RunControlError(str(exc)) from exc
        request.answer_json = resolved
        request.status = "defaulted" if use_default else "answered"
        request.answered_at = datetime.now(UTC)
        version = (
            self.db.scalar(
                select(func.max(TaskInputVersion.version)).where(
                    TaskInputVersion.task_id == task.id
                )
            )
            or 0
        ) + 1
        self.db.add(
            TaskInputVersion(
                id=f"task_input_{task.id}_{version}",
                task_id=task.id,
                version=version,
                input_json={
                    "base_input": task.input_json,
                    "clarification": {
                        "round": request.round_number,
                        "answer": resolved,
                        "used_default": use_default,
                    },
                },
                source="clarification_default" if use_default else "clarification_answer",
                created_at=datetime.now(UTC),
            )
        )
        target = RunState.RUNNING if request.blocking else None
        return ProtocolService(self.db).server_event(
            run.id,
            event_type="clarification.timed_out" if use_default else "clarification.answered",
            target_state=target,
            actor_type="system" if use_default else "publisher",
            actor_id=None if use_default else publisher.id,
            payload={
                "clarification_id": request.id,
                "round": request.round_number,
                "answer": resolved,
                "used_default": use_default,
            },
            idempotency_key=f"clarification:{request.id}:{'default' if use_default else 'answer'}",
            deliver_to_agent=True,
        )

    def decide_budget(
        self, publisher: User, run_id: str, request_id: str, *, approve: bool
    ) -> RunEvent:
        run, task = self.visible_run(publisher, run_id, lock=True)
        if task.publisher_id != publisher.id:
            raise RunControlError("publisher_required")
        request = self.db.scalar(
            select(BudgetExtensionRequest)
            .where(
                BudgetExtensionRequest.id == request_id,
                BudgetExtensionRequest.run_id == run.id,
            )
            .with_for_update()
        )
        if request is None or request.status != "pending":
            raise RunControlError("budget_request_not_pending")
        request.status = "approved" if approve else "rejected"
        request.decided_at = datetime.now(UTC)
        if approve:
            try:
                LedgerService(self.db).hold(
                    task.publisher_id,
                    task.id,
                    request.requested_tokens,
                    increase=True,
                    operation_id=f"budget:{request.id}",
                )
            except LedgerError as exc:
                self.db.rollback()
                raise RunControlError(str(exc)) from exc
            task.budget_tokens += request.requested_tokens
        return ProtocolService(self.db).server_event(
            run.id,
            event_type=f"budget_extension.{'approved' if approve else 'rejected'}",
            target_state=RunState.RUNNING,
            actor_type="publisher",
            actor_id=publisher.id,
            payload={"request_id": request.id, "requested_tokens": request.requested_tokens},
            idempotency_key=f"budget:{request.id}:{request.status}",
            deliver_to_agent=True,
        )

    def cancel(self, publisher: User, run_id: str) -> RunEvent:
        run, task = self.visible_run(publisher, run_id, lock=True)
        if task.publisher_id != publisher.id:
            raise RunControlError("publisher_required")
        before_accept = RunState(run.state) in {
            RunState.CANDIDATE_SELECTED,
            RunState.OFFER_SENT,
        }
        return ProtocolService(self.db).server_event(
            run.id,
            event_type="task.cancelled" if before_accept else "task.cancel_requested",
            target_state=RunState.CANCELLED if before_accept else RunState.CANCELLATION_REQUESTED,
            actor_type="publisher",
            actor_id=publisher.id,
            payload={"before_accept": before_accept},
            idempotency_key=f"cancel:{run.id}",
            deliver_to_agent=not before_accept,
        )

    def default_expired_clarifications(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        pending = list(
            self.db.scalars(
                select(ClarificationRequest).where(ClarificationRequest.status == "pending")
            )
        )
        count = 0
        for request in pending:
            if _aware(request.deadline) <= current:
                run = self.db.get(Run, request.run_id)
                task = self.db.get(Task, run.task_id) if run else None
                publisher = self.db.get(User, task.publisher_id) if task else None
                if publisher is not None:
                    self.answer_clarification(
                        publisher, request.run_id, request.id, {}, use_default=True
                    )
                    count += 1
        return count

    def sweep_deadlines(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        runs = list(
            self.db.scalars(
                select(Run).where(
                    Run.state.not_in(
                        [
                            RunState.COMPLETED,
                            RunState.CANCELLED,
                            RunState.FAILED,
                            RunState.TIMED_OUT,
                        ]
                    )
                )
            )
        )
        count = 0
        for run in runs:
            offer_expired = (
                run.state == RunState.OFFER_SENT and _aware(run.offer_expires_at) <= current
            )
            completion_expired = run.state in {
                RunState.ACCEPTED,
                RunState.RUNNING,
                RunState.WAITING_FOR_CLARIFICATION,
                RunState.WAITING_FOR_BUDGET,
                RunState.REWORKING,
                RunState.CANCELLATION_REQUESTED,
                RunState.AGENT_UNREACHABLE,
            } and _aware(run.completion_deadline) <= current
            if offer_expired or completion_expired:
                ProtocolService(self.db).server_event(
                    run.id,
                    event_type="task.timed_out",
                    target_state=RunState.TIMED_OUT,
                    actor_type="system",
                    actor_id=None,
                    payload={"reason": "offer_expired" if offer_expired else "deadline_expired"},
                    idempotency_key=f"timeout:{run.id}:{'offer' if offer_expired else 'deadline'}",
                    deliver_to_agent=not offer_expired,
                )
                count += 1
        return count

    def mark_unreachable_agents(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(minutes=5)
        pull_agents = list(
            self.db.scalars(
                select(AgentEndpoint.agent_id).where(
                    AgentEndpoint.endpoint_type == "pull",
                    AgentEndpoint.status == "verified",
                )
            )
        )
        count = 0
        for agent_id in set(pull_agents):
            connection = self.db.scalar(
                select(AgentConnection)
                .where(AgentConnection.agent_id == agent_id)
                .order_by(AgentConnection.generation.desc())
                .limit(1)
            )
            last_seen = connection.heartbeat_at if connection is not None else None
            disconnected = connection is None or connection.disconnected_at is not None
            stale = last_seen is None or _aware(last_seen) <= cutoff
            if not (disconnected and stale):
                continue
            active_runs = list(
                self.db.scalars(
                    select(Run).where(
                        Run.agent_id == agent_id,
                        Run.state.in_(
                            [
                                RunState.ACCEPTED,
                                RunState.RUNNING,
                                RunState.WAITING_FOR_CLARIFICATION,
                                RunState.WAITING_FOR_BUDGET,
                                RunState.REWORKING,
                                RunState.CANCELLATION_REQUESTED,
                            ]
                        ),
                    )
                )
            )
            for run in active_runs:
                previous = run.state
                generation = connection.generation if connection else 0
                ProtocolService(self.db).server_event(
                    run.id,
                    event_type="agent.unreachable",
                    target_state=RunState.AGENT_UNREACHABLE,
                    actor_type="system",
                    actor_id=None,
                    payload={"previous_state": previous},
                    idempotency_key=f"unreachable:{run.id}:{generation}",
                )
                count += 1
        return count

    def recover_agent(self, agent_id: str) -> int:
        runs = list(
            self.db.scalars(
                select(Run).where(
                    Run.agent_id == agent_id, Run.state == RunState.AGENT_UNREACHABLE
                )
            )
        )
        count = 0
        for run in runs:
            event = self.db.scalar(
                select(RunEvent)
                .where(RunEvent.run_id == run.id, RunEvent.event_type == "agent.unreachable")
                .order_by(RunEvent.sequence.desc())
                .limit(1)
            )
            previous = RunState(str(event.payload_json["previous_state"])) if event else None
            if previous is None:
                continue
            assert event is not None
            ProtocolService(self.db).server_event(
                run.id,
                event_type="agent.connection_restored",
                target_state=previous,
                actor_type="system",
                actor_id=None,
                payload={},
                idempotency_key=f"recovered:{run.id}:{event.id}",
                deliver_to_agent=True,
            )
            count += 1
        return count
