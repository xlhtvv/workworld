from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from workworld_api.dependencies import CurrentUser, Database
from workworld_api.domain.visibility import visible_input
from workworld_api.market_models import Agent
from workworld_api.services.tasks import TaskError, TaskService
from workworld_api.task_models import Application, Recommendation, Run, Task

router = APIRouter(prefix="/v1", tags=["tasks"])


class CreateTask(BaseModel):
    schema_id: str
    schema_version: str
    title: str = Field(min_length=1, max_length=200)
    public_summary: str = Field(min_length=1, max_length=5000)
    input_json: dict[str, Any]
    field_visibility: dict[str, Literal["public", "applicants", "winner"]]
    difficulty: str
    acceptance_rules: dict[str, Any]
    budget_tokens: int = Field(gt=0)
    recruitment_deadline: datetime | None = None
    completion_deadline: datetime
    assignment_mode: Literal["recommended", "open_call"]
    data_disclosure_acknowledged: bool

    @model_validator(mode="after")
    def disclosure_is_required(self) -> "CreateTask":
        if not self.data_disclosure_acknowledged:
            raise ValueError("provider_data_disclosure_must_be_acknowledged")
        return self


class ApplyBody(BaseModel):
    offering_version_id: str
    estimated_tokens_min: int = Field(ge=0)
    estimated_tokens_max: int = Field(ge=0)
    estimated_completion_seconds: int = Field(gt=0)
    message: str = Field(max_length=2000)
    valid_until: datetime


@router.post("/tasks", status_code=201)
def create_task(body: CreateTask, user: CurrentUser, db: Database) -> dict[str, object]:
    payload = body.model_dump(exclude={"data_disclosure_acknowledged"})
    try:
        task = TaskService(db).create(user, **payload)
    except TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": task.id, "status": task.status, "assignment_mode": task.assignment_mode}


@router.get("/tasks/open")
def open_tasks(db: Database) -> list[dict[str, object]]:
    tasks = db.scalars(select(Task).where(Task.status == "open"))
    return [
        {
            "id": task.id,
            "title": task.title,
            "summary": task.public_summary,
            "schema_id": task.schema_id,
            "schema_version": task.schema_version,
            "budget_tokens": task.budget_tokens,
            "recruitment_deadline": task.recruitment_deadline,
            "completion_deadline": task.completion_deadline,
            "input": visible_input(task.input_json, task.field_visibility, "public"),
        }
        for task in tasks
    ]


@router.get("/tasks")
def own_tasks(user: CurrentUser, db: Database) -> list[dict[str, object]]:
    published = list(db.scalars(select(Task).where(Task.publisher_id == user.id)))
    application_task_ids = list(
        db.scalars(select(Application.task_id).where(Application.provider_id == user.id))
    )
    agent_ids = select(Agent.id).where(Agent.owner_id == user.id)
    winning_task_ids = list(db.scalars(select(Run.task_id).where(Run.agent_id.in_(agent_ids))))
    involved_ids = set(application_task_ids + winning_task_ids)
    involved = (
        list(db.scalars(select(Task).where(Task.id.in_(involved_ids)))) if involved_ids else []
    )
    rows = {task.id: task for task in [*published, *involved]}
    return [
        {
            "id": task.id,
            "title": task.title,
            "schema_id": task.schema_id,
            "status": task.status,
            "assignment_mode": task.assignment_mode,
            "budget_tokens": task.budget_tokens,
            "completion_deadline": task.completion_deadline,
        }
        for task in sorted(rows.values(), key=lambda item: item.created_at, reverse=True)
    ]


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, user: CurrentUser, db: Database) -> dict[str, object]:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    level: Literal["public", "applicants", "winner"] = "public"
    if task.publisher_id == user.id:
        level = "winner"
    else:
        winning = db.scalar(
            select(Run.id)
            .join(Agent, Agent.id == Run.agent_id)
            .where(Run.task_id == task.id, Agent.owner_id == user.id)
            .limit(1)
        )
        application = db.scalar(
            select(Application.id).where(
                Application.task_id == task.id, Application.provider_id == user.id
            )
        )
        if winning is not None:
            level = "winner"
        elif application is not None:
            level = "applicants"
        elif task.status != "open":
            raise HTTPException(status_code=404, detail="task_not_found")
    result: dict[str, object] = {
        "id": task.id,
        "title": task.title,
        "public_summary": task.public_summary,
        "schema_id": task.schema_id,
        "schema_version": task.schema_version,
        "input": visible_input(task.input_json, task.field_visibility, level),
        "budget_tokens": task.budget_tokens,
        "status": task.status,
        "assignment_mode": task.assignment_mode,
        "completion_deadline": task.completion_deadline,
    }
    if task.publisher_id == user.id:
        result["recommendations"] = [
            {
                "offering_version_id": row.offering_version_id,
                "rank": row.rank,
                "score": row.score,
                "explanation": row.explanation_json,
            }
            for row in db.scalars(
                select(Recommendation)
                .where(Recommendation.task_id == task.id)
                .order_by(Recommendation.rank)
            )
        ]
        result["applications"] = [
            {
                "id": row.id,
                "offering_version_id": row.offering_version_id,
                "estimated_tokens_min": row.estimated_tokens_min,
                "estimated_tokens_max": row.estimated_tokens_max,
                "estimated_completion_seconds": row.estimated_completion_seconds,
                "message": row.message,
                "valid_until": row.valid_until,
                "status": row.status,
            }
            for row in db.scalars(
                select(Application)
                .where(Application.task_id == task.id)
                .order_by(Application.created_at)
            )
        ]
    run = db.scalar(
        select(Run).where(Run.task_id == task.id).order_by(Run.attempt.desc()).limit(1)
    )
    if run is not None:
        result["run"] = {"id": run.id, "attempt": run.attempt, "state": run.state}
    return result


@router.post("/tasks/{task_id}/applications", status_code=201)
def apply(task_id: str, body: ApplyBody, user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        application = TaskService(db).apply(
            user,
            task_id,
            body.offering_version_id,
            **body.model_dump(exclude={"offering_version_id"}),
        )
    except TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": application.id, "status": application.status}


@router.get("/applications")
def own_applications(user: CurrentUser, db: Database) -> list[dict[str, object]]:
    rows = db.scalars(select(Application).where(Application.provider_id == user.id))
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "offering_version_id": row.offering_version_id,
            "estimated_tokens_min": row.estimated_tokens_min,
            "estimated_tokens_max": row.estimated_tokens_max,
            "status": row.status,
        }
        for row in rows
    ]


@router.get("/tasks/{task_id}/applications")
def task_applications(task_id: str, user: CurrentUser, db: Database) -> list[dict[str, object]]:
    task = db.get(Task, task_id)
    if task is None or task.publisher_id != user.id:
        raise HTTPException(status_code=404, detail="task_not_found")
    rows = db.scalars(select(Application).where(Application.task_id == task_id))
    return [
        {
            "id": row.id,
            "offering_version_id": row.offering_version_id,
            "estimated_tokens_min": row.estimated_tokens_min,
            "estimated_tokens_max": row.estimated_tokens_max,
            "estimated_completion_seconds": row.estimated_completion_seconds,
            "message": row.message,
            "valid_until": row.valid_until,
            "status": row.status,
        }
        for row in rows
    ]


@router.post("/tasks/{task_id}/applications/{application_id}/select")
def select_application(
    task_id: str, application_id: str, user: CurrentUser, db: Database
) -> dict[str, str]:
    try:
        run = TaskService(db).select_application(user, task_id, application_id)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run.id, "state": run.state}


@router.post("/tasks/{task_id}/offerings/{version_id}/select")
def select_recommended(
    task_id: str, version_id: str, user: CurrentUser, db: Database
) -> dict[str, str]:
    try:
        run = TaskService(db).select_recommended(user, task_id, version_id)
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run.id, "state": run.state}
