from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from workworld_api.dependencies import AppSettings, CurrentAgent, Database
from workworld_api.models import User
from workworld_api.routers.agent_socket import PROTOCOL_VALIDATOR
from workworld_api.routers.artifacts import CompleteUpload, view
from workworld_api.routers.artifacts import service as artifact_service
from workworld_api.services.agents import AgentError, AgentService
from workworld_api.services.artifacts import ArtifactError
from workworld_api.services.protocol import ProtocolError, ProtocolService

router = APIRouter(prefix="/v1/agent-callbacks", tags=["agent-push"])


class AgentEnvelope(BaseModel):
    protocol_version: str
    message_id: str
    idempotency_key: str
    timestamp: str
    agent_id: str
    run_id: str
    type: str
    sequence: int
    payload: dict[str, Any]


class AgentBeginUpload(BaseModel):
    original_name: str = Field(min_length=1, max_length=500)
    kind: Literal[
        "text",
        "json",
        "image",
        "document",
        "spreadsheet",
        "audio",
        "video",
        "archive",
        "repository_snapshot",
        "generic_file",
    ]
    direction: Literal["output"]
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    task_id: str | None = None


class AgentCapacity(BaseModel):
    status: Literal["online", "offline", "draining"]
    max_concurrent_runs: int = Field(ge=0)
    active_runs: int = Field(ge=0)
    queue_capacity: int = Field(ge=0)
    estimated_wait_seconds: int = Field(ge=0)
    supported_offering_versions: list[str] = Field(default_factory=list)


@router.post("/capacity", status_code=204)
def update_capacity(body: AgentCapacity, agent: CurrentAgent, db: Database) -> None:
    try:
        AgentService(db).capacity(agent, **body.model_dump())
    except AgentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/events", status_code=202)
def callback(body: AgentEnvelope, agent: CurrentAgent, db: Database) -> dict[str, object]:
    envelope = body.model_dump()
    errors = list(PROTOCOL_VALIDATOR.iter_errors(envelope))
    if errors:
        first = errors[0]
        raise HTTPException(status_code=422, detail=f"invalid_protocol_message:{first.json_path}")
    if envelope["agent_id"] != agent.id:
        raise HTTPException(status_code=403, detail="agent_identity_mismatch")
    try:
        event = ProtocolService(db).ingest_agent_message(agent.id, envelope)
    except ProtocolError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"event_id": event.id, "sequence": event.sequence, "accepted": True}


def agent_owner(agent: CurrentAgent, db: Database) -> User:
    owner = db.get(User, agent.owner_id)
    if owner is None:
        raise HTTPException(status_code=401, detail="agent_owner_not_found")
    return owner


@router.post("/artifacts/uploads", status_code=201)
def begin_artifact(
    body: AgentBeginUpload,
    agent: CurrentAgent,
    db: Database,
    settings: AppSettings,
) -> dict[str, object]:
    try:
        artifact = artifact_service(db, settings).begin(
            agent_owner(agent, db), **body.model_dump()
        )
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**view(artifact), "upload_id": artifact.multipart_upload_id}


@router.post("/artifacts/{artifact_id}/parts/{part_number}")
def sign_artifact_part(
    artifact_id: str,
    part_number: int,
    agent: CurrentAgent,
    db: Database,
    settings: AppSettings,
) -> dict[str, str]:
    try:
        url = artifact_service(db, settings).signed_part(
            agent_owner(agent, db), artifact_id, part_number
        )
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"url": url}


@router.post("/artifacts/{artifact_id}/complete")
def complete_artifact(
    artifact_id: str,
    body: CompleteUpload,
    agent: CurrentAgent,
    db: Database,
    settings: AppSettings,
) -> dict[str, object]:
    try:
        artifact = artifact_service(db, settings).complete(
            agent_owner(agent, db), artifact_id, body.parts
        )
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return view(artifact)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    agent: CurrentAgent,
    db: Database,
    settings: AppSettings,
) -> dict[str, str]:
    try:
        url = artifact_service(db, settings).download_url(
            agent_owner(agent, db), artifact_id
        )
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"url": url}
