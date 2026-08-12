import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from workworld_api.database import session_factory
from workworld_api.dependencies import CurrentUser, Database
from workworld_api.finance_models import LedgerTransaction, QualityEvaluation
from workworld_api.models import Artifact
from workworld_api.services.acceptance import AcceptanceError, AcceptanceService
from workworld_api.services.run_control import RunControlError, RunControlService
from workworld_api.task_models import BudgetExtensionRequest, ClarificationRequest, RunEvent

router = APIRouter(prefix="/v1/runs", tags=["runs"])


class ClarificationAnswer(BaseModel):
    answer: dict[str, Any]


class BudgetDecision(BaseModel):
    approve: bool


class ReworkBody(BaseModel):
    reason: str
    acceptance_rule_refs: list[str]


def event_view(event: RunEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "sequence": event.sequence,
        "type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "payload": event.payload_json,
        "created_at": event.created_at,
    }


@router.get("/{run_id}")
def run_detail(run_id: str, user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        run, task = RunControlService(db).visible_run(user, run_id)
    except RunControlError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    evaluation = db.scalar(
        select(QualityEvaluation)
        .where(QualityEvaluation.run_id == run.id)
        .order_by(QualityEvaluation.round_number.desc())
        .limit(1)
    )
    clarifications = list(
        db.scalars(
            select(ClarificationRequest)
            .where(ClarificationRequest.run_id == run.id)
            .order_by(ClarificationRequest.round_number)
        )
    )
    budget_requests = list(
        db.scalars(
            select(BudgetExtensionRequest)
            .where(BudgetExtensionRequest.run_id == run.id)
            .order_by(BudgetExtensionRequest.created_at)
        )
    )
    artifacts = list(db.scalars(select(Artifact).where(Artifact.task_id == task.id)))
    ledger = list(
        db.scalars(
            select(LedgerTransaction)
            .where(
                LedgerTransaction.reference_type == "task",
                LedgerTransaction.reference_id == task.id,
            )
            .order_by(LedgerTransaction.created_at)
        )
    )
    return {
        "id": run.id,
        "task_id": task.id,
        "attempt": run.attempt,
        "state": run.state,
        "schema_version_id": run.schema_version_id,
        "offer_expires_at": run.offer_expires_at,
        "completion_deadline": run.completion_deadline,
        "acceptance_deadline": run.acceptance_deadline,
        "measured_tokens": run.measured_tokens,
        "quality_score": run.quality_score,
        "rework_count": run.rework_count,
        "acceptance_rules": task.acceptance_rules,
        "evaluation": (
            {
                "mode": evaluation.evaluation_mode,
                "model": evaluation.model,
                "rubric_version_id": evaluation.rubric_version_id,
                "score": evaluation.quality_score,
                "evidence": evaluation.evidence_json,
                "issues": evaluation.issues_json,
                "input_hash": evaluation.input_hash,
                "response_hash": evaluation.response_hash,
            }
            if evaluation
            else None
        ),
        "clarifications": [
            {
                "id": row.id,
                "round": row.round_number,
                "question": row.question,
                "answer_schema": row.answer_schema,
                "default_answer": row.default_answer,
                "status": row.status,
                "deadline": row.deadline,
                "answer": row.answer_json,
            }
            for row in clarifications
        ],
        "budget_requests": [
            {
                "id": row.id,
                "requested_tokens": row.requested_tokens,
                "reason": row.reason,
                "status": row.status,
            }
            for row in budget_requests
        ],
        "artifacts": [
            {
                "id": row.id,
                "direction": row.direction,
                "kind": row.kind,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "scan_status": row.scan_status,
                "metadata": row.metadata_json,
                "deleted_at": row.deleted_at,
            }
            for row in artifacts
        ],
        "ledger_transactions": [
            {
                "id": row.id,
                "type": row.transaction_type,
                "metadata": row.metadata_json,
                "created_at": row.created_at,
            }
            for row in ledger
        ],
    }


@router.get("/{run_id}/events")
def events(run_id: str, user: CurrentUser, db: Database, after: int = 0) -> list[dict[str, object]]:
    try:
        return [event_view(event) for event in RunControlService(db).events(user, run_id, after)]
    except RunControlError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def event_stream(
    request: Request, user_id: str, run_id: str, after: int
) -> AsyncIterator[str]:
    cursor = after
    idle_ticks = 0
    while not await request.is_disconnected():
        with session_factory()() as db:
            from workworld_api.models import User

            user = db.get(User, user_id)
            if user is None:
                return
            try:
                rows = RunControlService(db).events(user, run_id, cursor)
            except RunControlError:
                return
            for row in rows:
                cursor = row.sequence
                data = json.dumps(event_view(row), default=str, separators=(",", ":"))
                yield f"id: {row.sequence}\nevent: {row.event_type}\ndata: {data}\n\n"
                idle_ticks = 0
        idle_ticks += 1
        if idle_ticks >= 15:
            yield ": keepalive\n\n"
            idle_ticks = 0
        await asyncio.sleep(1)


@router.get("/{run_id}/events/stream")
def stream(
    run_id: str,
    request: Request,
    user: CurrentUser,
    db: Database,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        RunControlService(db).visible_run(user, run_id)
        after = max(0, int(last_event_id or 0))
    except (RunControlError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="run_not_found") from exc
    return StreamingResponse(
        event_stream(request, user.id, run_id, after), media_type="text/event-stream"
    )


@router.post("/{run_id}/clarifications/{clarification_id}/answer")
def answer_clarification(
    run_id: str,
    clarification_id: str,
    body: ClarificationAnswer,
    user: CurrentUser,
    db: Database,
) -> dict[str, object]:
    try:
        event = RunControlService(db).answer_clarification(
            user, run_id, clarification_id, body.answer
        )
    except RunControlError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return event_view(event)


@router.post("/{run_id}/budget-requests/{request_id}/decision")
def decide_budget(
    run_id: str,
    request_id: str,
    body: BudgetDecision,
    user: CurrentUser,
    db: Database,
) -> dict[str, object]:
    try:
        event = RunControlService(db).decide_budget(
            user, run_id, request_id, approve=body.approve
        )
    except RunControlError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return event_view(event)


@router.post("/{run_id}/cancel")
def cancel(run_id: str, user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        event = RunControlService(db).cancel(user, run_id)
    except (RunControlError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return event_view(event)


@router.post("/{run_id}/accept")
def accept_result(run_id: str, user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        run = AcceptanceService(db).accept(user, run_id)
    except AcceptanceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run.id, "state": run.state, "settled_tokens": run.measured_tokens}


@router.post("/{run_id}/rework", status_code=201)
def request_rework(
    run_id: str, body: ReworkBody, user: CurrentUser, db: Database
) -> dict[str, object]:
    try:
        request = AcceptanceService(db).request_rework(
            user, run_id, body.reason, body.acceptance_rule_refs
        )
    except AcceptanceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": request.id, "run_id": request.run_id}
