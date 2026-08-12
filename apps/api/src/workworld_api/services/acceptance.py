import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from workworld_api.domain.run_state import RunState
from workworld_api.market_models import Agent
from workworld_api.models import Artifact, ScanStatus, User
from workworld_api.schema_catalog import get_schema
from workworld_api.services.artifact_retention import mark_settled
from workworld_api.services.ledger import LedgerError, LedgerService
from workworld_api.services.metering import UNIT_RATES, unit_quantity
from workworld_api.services.protocol import ProtocolService
from workworld_api.task_models import ReworkRequest, Run, RunEvent, Task


class AcceptanceError(ValueError):
    pass


class AcceptanceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def accept(self, publisher: User, run_id: str, *, automatic: bool = False) -> Run:
        run = self.db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        task = self.db.get(Task, run.task_id) if run else None
        agent = self.db.get(Agent, run.agent_id) if run else None
        if run is None or task is None or agent is None or task.publisher_id != publisher.id:
            raise AcceptanceError("run_not_found")
        if run.state != RunState.WAITING_FOR_ACCEPTANCE or run.measured_tokens is None:
            raise AcceptanceError("run_not_awaiting_acceptance")
        try:
            LedgerService(self.db).settle(
                publisher.id, agent.owner_id, task.id, run.measured_tokens
            )
        except LedgerError as exc:
            self.db.rollback()
            raise AcceptanceError(str(exc)) from exc
        now = datetime.now(UTC)
        run.completed_at = now
        task.status = "completed"
        for artifact in self.db.scalars(select(Artifact).where(Artifact.task_id == task.id)):
            mark_settled(artifact, now)
        ProtocolService(self.db).server_event(
            run.id,
            event_type="task.completed",
            target_state=RunState.COMPLETED,
            actor_type="system" if automatic else "publisher",
            actor_id=None if automatic else publisher.id,
            payload={
                "automatic": automatic,
                "settled_tokens": run.measured_tokens,
            },
            idempotency_key=f"accept:{run.id}:{'auto' if automatic else 'publisher'}",
        )
        return run

    def request_rework(
        self,
        publisher: User,
        run_id: str,
        reason: str,
        acceptance_rule_refs: list[str],
    ) -> ReworkRequest:
        run = self.db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        task = self.db.get(Task, run.task_id) if run else None
        if run is None or task is None or task.publisher_id != publisher.id:
            raise AcceptanceError("run_not_found")
        if run.state != RunState.WAITING_FOR_ACCEPTANCE or run.rework_count >= 1:
            raise AcceptanceError("rework_not_available")
        if not reason.strip() or not acceptance_rule_refs:
            raise AcceptanceError("rework_reason_required")
        allowed_refs = set(task.acceptance_rules)
        if any(reference not in allowed_refs for reference in acceptance_rule_refs):
            raise AcceptanceError("rework_scope_expansion_forbidden")
        request = ReworkRequest(
            id=f"rework_{uuid.uuid4().hex}",
            run_id=run.id,
            reason=reason,
            acceptance_rule_refs=acceptance_rule_refs,
            created_at=datetime.now(UTC),
        )
        run.rework_count = 1
        self.db.add(request)
        ProtocolService(self.db).server_event(
            run.id,
            event_type="task.rework_requested",
            target_state=RunState.REWORK_REQUESTED,
            actor_type="publisher",
            actor_id=publisher.id,
            payload={
                "rework_id": request.id,
                "reason": reason,
                "acceptance_rule_refs": acceptance_rule_refs,
            },
            idempotency_key=f"rework:{run.id}:1",
            deliver_to_agent=True,
        )
        return request

    def auto_accept_due(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        runs = list(
            self.db.scalars(
                select(Run).where(
                    Run.state == RunState.WAITING_FOR_ACCEPTANCE,
                    Run.acceptance_deadline.is_not(None),
                    Run.acceptance_deadline <= current,
                )
            )
        )
        count = 0
        for run in runs:
            task = self.db.get(Task, run.task_id)
            publisher = self.db.get(User, task.publisher_id) if task else None
            if publisher is not None:
                self.accept(publisher, run.id, automatic=True)
                count += 1
        return count

    def settle_terminal_runs(self) -> int:
        runs = list(
            self.db.scalars(
                select(Run).where(
                    Run.state.in_([RunState.CANCELLED, RunState.FAILED, RunState.TIMED_OUT])
                )
            )
        )
        count = 0
        for run in runs:
            task = self.db.get(Task, run.task_id)
            agent = self.db.get(Agent, run.agent_id)
            if task is None or agent is None:
                continue
            ledger = LedgerService(self.db)
            held_account = ledger.user_accounts(task.publisher_id)["user_held"]
            held = ledger.task_held(held_account, task.id)
            if held <= 0:
                continue
            if run.state == RunState.CANCELLED:
                amount = self._verified_partial_amount(run, task, held)
                if amount > 0:
                    ledger.settle(
                        task.publisher_id,
                        agent.owner_id,
                        task.id,
                        amount,
                        partial=True,
                    )
                else:
                    ledger.refund(task.publisher_id, task.id)
            else:
                ledger.refund(task.publisher_id, task.id)
            task.status = str(run.state)
            now = datetime.now(UTC)
            for artifact in self.db.scalars(select(Artifact).where(Artifact.task_id == task.id)):
                mark_settled(artifact, now)
            self.db.commit()
            count += 1
        return count

    def _verified_partial_amount(self, run: Run, task: Task, held: int) -> int:
        schema = get_schema(task.schema_id, task.schema_version)
        if schema is None:
            return 0
        cancellation_requested_at = self.db.scalar(
            select(RunEvent.created_at)
            .where(
                RunEvent.run_id == run.id,
                RunEvent.event_type == "task.cancel_requested",
            )
            .order_by(RunEvent.sequence)
            .limit(1)
        )
        if cancellation_requested_at is None:
            return 0
        artifacts = list(
            self.db.scalars(
                select(Artifact).where(
                    Artifact.task_id == task.id,
                    Artifact.direction == "output",
                    Artifact.scan_status == ScanStatus.CLEAN,
                    Artifact.deleted_at.is_(None),
                    Artifact.created_at <= cancellation_requested_at,
                )
            )
        )
        if not artifacts:
            return 0
        unit = str(schema["metering"]["output_unit"])
        quantity = unit_quantity(unit, {}, [item.metadata_json for item in artifacts])
        amount = int(
            quantity
            * UNIT_RATES[unit]
            * Decimal(str(schema["difficulty_multipliers"][task.difficulty]))
            * Decimal("0.7")
        )
        return min(held, max(0, amount))
