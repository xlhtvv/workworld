import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from workworld_api.dependencies import CurrentAdmin, Database
from workworld_api.finance_models import (
    LedgerTransaction,
    MeteringFormulaVersion,
    QualityRubricVersion,
    TokenPolicyVersion,
)
from workworld_api.market_models import Agent, Offering, OfferingVersion
from workworld_api.models import Artifact, User
from workworld_api.reputation_models import AuditEvent
from workworld_api.services.ledger import LedgerError, LedgerService
from workworld_api.task_models import Run, Task

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdjustmentBody(BaseModel):
    user_id: str
    amount: int
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)


def record_admin_action(
    db: Database,
    admin: User,
    action: str,
    subject_type: str,
    subject_id: str,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditEvent(
            id=f"audit_{uuid.uuid4().hex}",
            actor_type="admin",
            actor_id=admin.id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            details_json=details or {},
            created_at=datetime.now(UTC),
        )
    )


@router.get("/system")
def system(_admin: CurrentAdmin, db: Database) -> dict[str, object]:
    return {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "agents": db.scalar(select(func.count(Agent.id))) or 0,
        "offerings": db.scalar(select(func.count(Offering.id))) or 0,
        "tasks": db.scalar(select(func.count(Task.id))) or 0,
        "runs": db.scalar(select(func.count(Run.id))) or 0,
        "artifacts": db.scalar(select(func.count(Artifact.id))) or 0,
        "ledger_transactions": db.scalar(select(func.count(LedgerTransaction.id))) or 0,
    }


@router.get("/users")
def users(_admin: CurrentAdmin, db: Database) -> list[dict[str, object]]:
    return [
        {"id": row.id, "email": row.email, "role": row.role, "suspended": row.suspended}
        for row in db.scalars(select(User).order_by(User.created_at.desc()).limit(200))
    ]


@router.get("/agents")
def agents(_admin: CurrentAdmin, db: Database) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "slug": row.slug,
            "status": row.status,
        }
        for row in db.scalars(select(Agent).order_by(Agent.created_at.desc()).limit(200))
    ]


@router.post("/agents/{agent_id}/suspend")
def suspend_agent(agent_id: str, admin: CurrentAdmin, db: Database) -> dict[str, object]:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent_not_found")
    agent.status = "suspended"
    record_admin_action(db, admin, "agent.suspended", "agent", agent.id)
    db.commit()
    return {"id": agent.id, "status": agent.status}


@router.get("/offerings")
def offerings(_admin: CurrentAdmin, db: Database) -> list[dict[str, object]]:
    return [
        {
            "id": offering.id,
            "owner_id": offering.owner_id,
            "agent_id": offering.agent_id,
            "slug": offering.slug,
            "status": offering.status,
            "version_id": version.id if version else None,
        }
        for offering, version in db.execute(
            select(Offering, OfferingVersion)
            .outerjoin(OfferingVersion, Offering.latest_version_id == OfferingVersion.id)
            .order_by(Offering.created_at.desc())
            .limit(200)
        )
    ]


@router.post("/offerings/{offering_id}/suspend")
def suspend_offering(
    offering_id: str, admin: CurrentAdmin, db: Database
) -> dict[str, object]:
    offering = db.get(Offering, offering_id)
    if offering is None:
        raise HTTPException(status_code=404, detail="offering_not_found")
    offering.status = "suspended"
    record_admin_action(db, admin, "offering.suspended", "offering", offering.id)
    db.commit()
    return {"id": offering.id, "status": offering.status}


@router.get("/tasks")
def tasks(_admin: CurrentAdmin, db: Database) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "publisher_id": row.publisher_id,
            "schema_id": row.schema_id,
            "status": row.status,
            "budget_tokens": row.budget_tokens,
        }
        for row in db.scalars(select(Task).order_by(Task.created_at.desc()).limit(200))
    ]


@router.get("/audit")
def audit(_admin: CurrentAdmin, db: Database) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "action": row.action,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "created_at": row.created_at,
        }
        for row in db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(500))
    ]


@router.get("/metering")
def metering(_admin: CurrentAdmin, db: Database) -> dict[str, object]:
    return {
        "formula_versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "definition": row.definition_json,
            }
            for row in db.scalars(
                select(MeteringFormulaVersion).order_by(MeteringFormulaVersion.created_at.desc())
            )
        ],
        "rubric_versions": [
            {
                "id": row.id,
                "schema_id": row.schema_id,
                "version": row.version,
                "status": row.status,
                "definition": row.definition_json,
            }
            for row in db.scalars(
                select(QualityRubricVersion).order_by(QualityRubricVersion.created_at.desc())
            )
        ],
        "token_policy_versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "definition": row.definition_json,
            }
            for row in db.scalars(
                select(TokenPolicyVersion).order_by(TokenPolicyVersion.created_at.desc())
            )
        ],
    }


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: str, admin: CurrentAdmin, db: Database) -> dict[str, object]:
    user = db.get(User, user_id)
    if user is None or user.id == admin.id:
        raise HTTPException(status_code=409, detail="user_not_suspendable")
    user.suspended = True
    record_admin_action(db, admin, "user.suspended", "user", user.id)
    db.commit()
    return {"id": user.id, "suspended": True}


@router.post("/ledger/adjustments", status_code=201)
def adjustment(body: AdjustmentBody, admin: CurrentAdmin, db: Database) -> dict[str, object]:
    if db.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    record_admin_action(
        db,
        admin,
        "ledger.adjusted",
        "user",
        body.user_id,
        {"amount": body.amount, "reason": body.reason, "idempotency_key": body.idempotency_key},
    )
    try:
        transaction = LedgerService(db).admin_adjust(
            body.user_id, body.amount, body.idempotency_key, body.reason
        )
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"transaction_id": transaction.id, "transaction_type": transaction.transaction_type}
