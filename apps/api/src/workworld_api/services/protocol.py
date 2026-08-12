import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from workworld_api.domain.run_state import RunState, ensure_transition
from workworld_api.ids import new_id
from workworld_api.services.moderation import ModerationBlocked, ModerationService
from workworld_api.services.result_validation import ResultValidationError, validate_result
from workworld_api.task_models import (
    Application,
    BudgetExtensionRequest,
    ClarificationRequest,
    ProtocolOutbox,
    Run,
    RunEvent,
    RunSlotReservation,
)


class ProtocolError(ValueError):
    pass


STATE_EVENTS: dict[str, RunState] = {
    "task.accept": RunState.ACCEPTED,
    "task.reject": RunState.OPEN,
    "task.started": RunState.RUNNING,
    "clarification.requested": RunState.WAITING_FOR_CLARIFICATION,
    "budget_extension.requested": RunState.WAITING_FOR_BUDGET,
    "task.result_submitted": RunState.RESULT_SUBMITTED,
    "task.cancelled": RunState.CANCELLED,
    "task.failed": RunState.FAILED,
}
PASSIVE_AGENT_EVENTS = {
    "task.progress",
    "artifact.upload_requested",
    "artifact.upload_completed",
}


class ProtocolService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ingest_agent_message(self, agent_id: str, envelope: dict[str, Any]) -> RunEvent:
        run_id = str(envelope["run_id"])
        idempotency_key = str(envelope["idempotency_key"])
        run = self.db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.agent_id != agent_id:
            raise ProtocolError("run_not_found")
        duplicate = self.db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return duplicate
        agent_sequence = int(envelope["sequence"])
        if agent_sequence != run.last_agent_sequence + 1:
            raise ProtocolError("agent_sequence_out_of_order")
        event_type = str(envelope["type"])
        if event_type == "task.completed":
            raise ProtocolError("agent_cannot_complete_run")
        payload = dict(envelope["payload"])
        self._validate_related_payload(run, event_type, payload)
        if event_type in STATE_EVENTS:
            target = STATE_EVENTS[event_type]
            if event_type == "task.started" and run.state == RunState.REWORK_REQUESTED:
                target = RunState.REWORKING
            changes_state = not (
                event_type == "clarification.requested" and not bool(payload.get("blocking", True))
            )
            if changes_state:
                try:
                    ensure_transition(RunState(run.state), target)
                except ValueError as exc:
                    raise ProtocolError("invalid_run_transition") from exc
                run.state = target
                if target == RunState.ACCEPTED:
                    run.accepted_at = datetime.now(UTC)
        elif event_type not in PASSIVE_AGENT_EVENTS:
            raise ProtocolError("agent_event_not_allowed")
        if event_type == "task.progress" and run.state not in {
            RunState.RUNNING,
            RunState.REWORKING,
            RunState.CANCELLATION_REQUESTED,
        }:
            raise ProtocolError("progress_not_allowed_in_state")
        self._related_record(run, event_type, payload)
        event = self._append(
            run,
            event_type=event_type,
            idempotency_key=idempotency_key,
            message_id=str(envelope["message_id"]),
            actor_type="agent",
            actor_id=agent_id,
            payload=payload,
            agent_sequence=agent_sequence,
        )
        run.last_agent_sequence = agent_sequence
        if event_type == "task.reject":
            from workworld_api.task_models import Task

            task = self.db.get(Task, run.task_id)
            if task is not None:
                task.status = "matching" if task.assignment_mode == "recommended" else "open"
                if task.assignment_mode == "open_call":
                    applications = self.db.scalars(
                        select(Application).where(Application.task_id == task.id)
                    )
                    for application in applications:
                        application.status = (
                            "rejected"
                            if application.offering_version_id == run.offering_version_id
                            else "submitted"
                        )
            self._release_slot(run.id)
        if run.state in {RunState.CANCELLED, RunState.FAILED, RunState.TIMED_OUT}:
            self._release_slot(run.id)
        self.db.commit()
        return event

    def server_event(
        self,
        run_id: str,
        *,
        event_type: str,
        target_state: RunState | None,
        actor_type: str,
        actor_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str,
        deliver_to_agent: bool = False,
    ) -> RunEvent:
        # Serialize every server-side mutation on the Run before checking the
        # idempotency key. Checking first leaves a race where two transactions
        # both observe a miss and the loser fails the unique constraint instead
        # of returning the already-recorded event.
        run = self.db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise ProtocolError("run_not_found")
        duplicate = self.db.scalar(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return duplicate
        if target_state is not None:
            try:
                ensure_transition(RunState(run.state), target_state)
            except ValueError as exc:
                raise ProtocolError("invalid_run_transition") from exc
            run.state = target_state
        event = self._append(
            run,
            event_type=event_type,
            idempotency_key=idempotency_key,
            message_id=str(uuid.uuid4()),
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
        )
        if deliver_to_agent:
            self.db.flush()
            self.db.add(
                ProtocolOutbox(
                    id=new_id("outbox"),
                    run_event_id=event.id,
                    agent_id=run.agent_id,
                    status="pending",
                    attempts=0,
                    available_at=datetime.now(UTC),
                )
            )
        if run.state in {
            RunState.COMPLETED,
            RunState.CANCELLED,
            RunState.FAILED,
            RunState.TIMED_OUT,
        }:
            self._release_slot(run.id)
        self.db.commit()
        return event

    def pending_outbox(
        self, agent_id: str, *, force: bool = False, limit: int = 100
    ) -> list[tuple[ProtocolOutbox, RunEvent]]:
        now = datetime.now(UTC)
        query = (
            select(ProtocolOutbox, RunEvent)
            .join(RunEvent, RunEvent.id == ProtocolOutbox.run_event_id)
            .where(
                ProtocolOutbox.agent_id == agent_id,
                ProtocolOutbox.status == "pending",
            )
            .order_by(RunEvent.created_at, RunEvent.sequence)
            .limit(limit)
            .with_for_update()
        )
        if not force:
            query = query.where(ProtocolOutbox.available_at <= now)
        rows = list(self.db.execute(query).tuples())
        for outbox, _event in rows:
            outbox.attempts += 1
            delay_seconds = min(30, 2 ** min(outbox.attempts, 5))
            outbox.available_at = now + timedelta(seconds=delay_seconds)
        self.db.commit()
        return rows

    def acknowledge_outbox(self, agent_id: str, event_ids: list[str]) -> int:
        if not event_ids:
            return 0
        rows = [
            row[0]
            for row in self.db.execute(
                select(ProtocolOutbox, RunEvent)
                .join(RunEvent, RunEvent.id == ProtocolOutbox.run_event_id)
                .where(
                    ProtocolOutbox.agent_id == agent_id,
                    ProtocolOutbox.status == "pending",
                    or_(
                        ProtocolOutbox.run_event_id.in_(set(event_ids)),
                        RunEvent.message_id.in_(set(event_ids)),
                    ),
                )
                .with_for_update()
            )
        ]
        now = datetime.now(UTC)
        for row in rows:
            row.status = "acknowledged"
            row.acknowledged_at = now
        self.db.commit()
        return len(rows)

    @staticmethod
    def event_envelope(event: RunEvent, agent_id: str) -> dict[str, Any]:
        return {
            "protocol_version": "1.0",
            "message_id": event.message_id,
            "idempotency_key": event.idempotency_key,
            "timestamp": event.created_at.isoformat(),
            "agent_id": agent_id,
            "run_id": event.run_id,
            "type": event.event_type,
            "sequence": event.sequence,
            "payload": event.payload_json,
        }

    def _append(
        self,
        run: Run,
        *,
        event_type: str,
        idempotency_key: str,
        message_id: str,
        actor_type: str,
        actor_id: str | None,
        payload: dict[str, Any],
        agent_sequence: int | None = None,
    ) -> RunEvent:
        event = RunEvent(
            id=new_id("event"),
            run_id=run.id,
            sequence=run.next_event_sequence,
            agent_sequence=agent_sequence,
            message_id=message_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload_json=payload,
            created_at=datetime.now(UTC),
        )
        run.next_event_sequence += 1
        self.db.add(event)
        return event

    def _related_record(self, run: Run, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "clarification.requested":
            if run.clarification_rounds >= 3:
                raise ProtocolError("clarification_round_limit")
            run.clarification_rounds += 1
            self.db.add(
                ClarificationRequest(
                    id=new_id("clarification"),
                    run_id=run.id,
                    round_number=run.clarification_rounds,
                    question=str(payload["question"]),
                    answer_schema=dict(payload["answer_schema"]),
                    default_answer=dict(payload["default_answer"]),
                    blocking=bool(payload.get("blocking", True)),
                    status="pending",
                    deadline=datetime.fromisoformat(str(payload["deadline"])),
                    created_at=datetime.now(UTC),
                )
            )
        elif event_type == "budget_extension.requested":
            requested = int(payload["requested_tokens"])
            self.db.add(
                BudgetExtensionRequest(
                    id=new_id("budget"),
                    run_id=run.id,
                    requested_tokens=requested,
                    reason=str(payload["reason"]),
                    status="pending",
                    created_at=datetime.now(UTC),
                )
            )

    def _validate_related_payload(
        self, run: Run, event_type: str, payload: dict[str, Any]
    ) -> None:
        try:
            if event_type == "clarification.requested":
                if run.clarification_rounds >= 3:
                    raise ProtocolError("clarification_round_limit")
                if not str(payload["question"]).strip():
                    raise ProtocolError("clarification_invalid")
                if not isinstance(payload["answer_schema"], dict) or not isinstance(
                    payload["default_answer"], dict
                ):
                    raise ProtocolError("clarification_invalid")
                deadline = datetime.fromisoformat(str(payload["deadline"]))
                if deadline.tzinfo is None:
                    raise ProtocolError("clarification_deadline_timezone_required")
                try:
                    ModerationService(self.db).check_text(
                        "clarification", f"{run.id}:{run.clarification_rounds + 1}",
                        json.dumps(
                            {
                                "question": payload["question"],
                                "default_answer": payload["default_answer"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                except ModerationBlocked as exc:
                    raise ProtocolError(str(exc)) from exc
            elif event_type == "budget_extension.requested":
                if int(payload["requested_tokens"]) <= 0 or not str(payload["reason"]).strip():
                    raise ProtocolError("budget_extension_invalid")
                try:
                    ModerationService(self.db).check_text(
                        "budget_extension", f"{run.id}:{run.last_agent_sequence + 1}",
                        str(payload["reason"]),
                    )
                except ModerationBlocked as exc:
                    raise ProtocolError(str(exc)) from exc
            elif event_type == "task.result_submitted":
                try:
                    validate_result(self.db, run, payload)
                except ResultValidationError as exc:
                    raise ProtocolError(str(exc)) from exc
                try:
                    ModerationService(self.db).check_text(
                        "task_result", f"{run.id}:{run.rework_count + 1}",
                        json.dumps(payload["output"], ensure_ascii=False, sort_keys=True),
                    )
                except ModerationBlocked as exc:
                    raise ProtocolError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ProtocolError):
                raise
            raise ProtocolError(f"{event_type}_payload_invalid") from exc

    def _release_slot(self, run_id: str) -> None:
        slot = self.db.scalar(
            select(RunSlotReservation).where(
                RunSlotReservation.run_id == run_id,
                RunSlotReservation.status == "active",
            )
        )
        if slot is not None:
            slot.status = "released"
            slot.released_at = datetime.now(UTC)
