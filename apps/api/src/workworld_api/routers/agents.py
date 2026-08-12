import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from workworld_api.database import session_factory
from workworld_api.dependencies import AppSettings, CurrentUser, Database
from workworld_api.market_models import (
    Agent,
    AgentCapacitySnapshot,
    AgentEndpoint,
    Offering,
    OfferingCertification,
    OfferingVersion,
)
from workworld_api.models import Artifact, User
from workworld_api.services.agents import AgentError, AgentService, OfferingService
from workworld_api.services.certification import (
    CertificationError,
    OfferingCertificationService,
)
from workworld_api.services.endpoint_security import ValidatedEndpoint
from workworld_api.services.pull_certification import pull_certifications
from workworld_api.services.s3_store import S3ArtifactStore

router = APIRouter(prefix="/v1", tags=["agents"])


class CreateAgent(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)


class CreateEndpoint(BaseModel):
    endpoint_type: Literal["pull", "push"]
    url: str | None = Field(default=None, max_length=2048)


class OfferingVersionBody(BaseModel):
    offering_id: str | None = None
    slug: str = Field(min_length=1, max_length=160)
    agent_id: str
    schema_id: str
    schema_version: str
    name_i18n: dict[str, str]
    description_i18n: dict[str, str]
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    example_artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    risk_disclosure: str = Field(min_length=1, max_length=5000)
    output_license: str = Field(min_length=1, max_length=200)
    sla_seconds: int = Field(ge=1, le=2_592_000)
    input_limits: dict[str, Any] = Field(default_factory=dict)
    estimated_tokens_min: int = Field(ge=0)
    estimated_tokens_max: int = Field(ge=0)
    estimated_seconds_min: int = Field(ge=1)
    estimated_seconds_max: int = Field(ge=1)
    auto_apply_policy: dict[str, Any] = Field(default_factory=dict)


@router.post("/agents", status_code=201)
def create_agent(body: CreateAgent, user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        agent = AgentService(db).create(user, body.name, body.slug)
        return {"id": agent.id, "name": agent.name, "slug": agent.slug, "status": agent.status}
    except AgentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/agents")
def list_agents(user: CurrentUser, db: Database) -> list[dict[str, object]]:
    agents = db.scalars(select(Agent).where(Agent.owner_id == user.id))
    return [
        {"id": agent.id, "name": agent.name, "slug": agent.slug, "status": agent.status}
        for agent in agents
    ]


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str, user: CurrentUser, db: Database) -> dict[str, object]:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.owner_id != user.id:
        raise HTTPException(status_code=404, detail="agent_not_found")
    endpoints = list(
        db.scalars(select(AgentEndpoint).where(AgentEndpoint.agent_id == agent.id))
    )
    capacity = db.scalar(
        select(AgentCapacitySnapshot)
        .where(AgentCapacitySnapshot.agent_id == agent.id)
        .order_by(AgentCapacitySnapshot.observed_at.desc())
        .limit(1)
    )
    offerings = list(db.scalars(select(Offering).where(Offering.agent_id == agent.id)))
    return {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "status": agent.status,
        "endpoints": [
            {"id": row.id, "type": row.endpoint_type, "url": row.url, "status": row.status}
            for row in endpoints
        ],
        "capacity": (
            {
                "status": capacity.status,
                "max_concurrent_runs": capacity.max_concurrent_runs,
                "active_runs": capacity.active_runs,
                "queue_capacity": capacity.queue_capacity,
                "estimated_wait_seconds": capacity.estimated_wait_seconds,
            }
            if capacity
            else None
        ),
        "offerings": [
            {"id": row.id, "slug": row.slug, "status": row.status} for row in offerings
        ],
    }


@router.post("/agents/{agent_id}/credentials", status_code=201)
def issue_credential(agent_id: str, user: CurrentUser, db: Database) -> dict[str, str]:
    try:
        credential, raw = AgentService(db).issue_credential(user, agent_id)
        return {"id": credential.id, "credential": raw, "prefix": credential.key_prefix}
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agents/credentials/{credential_id}", status_code=204)
def revoke_credential(credential_id: str, user: CurrentUser, db: Database) -> None:
    try:
        AgentService(db).revoke_credential(user, credential_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/endpoints", status_code=201)
def create_endpoint(
    agent_id: str,
    body: CreateEndpoint,
    user: CurrentUser,
    db: Database,
    settings: AppSettings,
) -> dict[str, object]:
    service = AgentService(db, settings=settings)
    try:
        if body.endpoint_type == "pull":
            endpoint = service.register_pull_endpoint(user, agent_id)
        else:
            if body.url is None:
                raise AgentError("push_url_required")
            endpoint = service.register_push_endpoint(user, agent_id, body.url)
        return {
            "id": endpoint.id,
            "type": endpoint.endpoint_type,
            "status": endpoint.status,
        }
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/offerings/versions", status_code=201)
def create_offering_version(
    body: OfferingVersionBody, user: CurrentUser, db: Database
) -> dict[str, object]:
    payload = body.model_dump(exclude={"offering_id", "slug", "agent_id"})
    try:
        offering, version = OfferingService(db).create_version(
            user, body.agent_id, body.slug, payload, body.offering_id
        )
        return {"offering_id": offering.id, "version_id": version.id, "version": version.version}
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/offerings/versions/{version_id}/publish")
def publish_offering(version_id: str, user: CurrentUser, db: Database) -> dict[str, str]:
    try:
        version = OfferingService(db).publish(user, version_id)
        return {"status": version.status}
    except AgentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/offerings/versions/{version_id}/certify")
async def certify_offering(
    version_id: str, user: CurrentUser, db: Database, settings: AppSettings
) -> dict[str, object]:
    version = db.get(OfferingVersion, version_id)
    offering = db.get(Offering, version.offering_id) if version else None
    if version is None or offering is None or offering.owner_id != user.id:
        raise HTTPException(status_code=409, detail="offering_version_not_certifiable")
    endpoint_types = set(
        db.scalars(
            select(AgentEndpoint.endpoint_type).where(
                AgentEndpoint.agent_id == offering.agent_id,
                AgentEndpoint.status == "verified",
            )
        )
    )
    endpoint_type: Literal["pull", "push"] = "push" if "push" in endpoint_types else "pull"
    owner_id = user.id
    agent_id = offering.agent_id
    loop = asyncio.get_running_loop()

    def execute() -> OfferingCertification:
        sender = None
        if endpoint_type == "pull":
            def pull_sender(
                _endpoint: ValidatedEndpoint, payload: object, _secret: str
            ) -> tuple[int, bytes]:
                future = asyncio.run_coroutine_threadsafe(
                    pull_certifications.request(agent_id, payload), loop
                )
                return 200, json.dumps(future.result(timeout=125)).encode()

            sender = pull_sender
        with session_factory()() as certification_db:
            owner = certification_db.get(User, owner_id)
            if owner is None:
                raise CertificationError("offering_version_not_certifiable")
            return OfferingCertificationService(
                certification_db,
                settings,
                endpoint_type=endpoint_type,
                sender=sender,
            ).run(owner, version_id)

    try:
        certification = await asyncio.to_thread(execute)
    except CertificationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": certification.id,
        "status": certification.status,
        "level": certification.level,
        "score": certification.score,
        "checks": certification.checks_json,
    }


@router.get("/marketplace")
def marketplace(db: Database) -> list[dict[str, object]]:
    rows = db.execute(
        select(Offering, OfferingVersion)
        .join(OfferingVersion, Offering.latest_version_id == OfferingVersion.id)
        .where(Offering.status == "published", OfferingVersion.status == "published")
    ).all()
    return [
        {
            "id": offering.id,
            "slug": offering.slug,
            "version_id": version.id,
            "schema_id": version.schema_id,
            "schema_version": version.schema_version,
            "name": version.name_i18n,
            "description": version.description_i18n,
            "example_artifact_ids": version.example_artifact_ids,
            "estimated_tokens": [version.estimated_tokens_min, version.estimated_tokens_max],
        }
        for offering, version in rows
    ]


@router.get("/marketplace/{offering_slug}")
def marketplace_detail(offering_slug: str, db: Database) -> dict[str, object]:
    row = db.execute(
        select(Offering, OfferingVersion)
        .join(OfferingVersion, Offering.latest_version_id == OfferingVersion.id)
        .where(
            or_(Offering.slug == offering_slug, Offering.id == offering_slug),
            Offering.status == "published",
            OfferingVersion.status == "published",
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="offering_not_found")
    offering, version = row
    certification = db.scalar(
        select(OfferingCertification)
        .where(
            OfferingCertification.offering_version_id == version.id,
            OfferingCertification.status == "passed",
        )
        .order_by(OfferingCertification.completed_at.desc())
        .limit(1)
    )
    return {
        "id": offering.id,
        "slug": offering.slug,
        "provider_id": offering.owner_id,
        "agent_id": offering.agent_id,
        "version_id": version.id,
        "version": version.version,
        "schema_id": version.schema_id,
        "schema_version": version.schema_version,
        "name": version.name_i18n,
        "description": version.description_i18n,
        "capabilities": version.capabilities,
        "example_artifacts": [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "metadata": artifact.metadata_json,
            }
            for artifact_id in version.example_artifact_ids
            if (artifact := db.get(Artifact, artifact_id)) is not None
        ],
        "risk_disclosure": version.risk_disclosure,
        "output_license": version.output_license,
        "sla_seconds": version.sla_seconds,
        "estimated_tokens": [version.estimated_tokens_min, version.estimated_tokens_max],
        "estimated_seconds": [version.estimated_seconds_min, version.estimated_seconds_max],
        "certification": (
            {"level": certification.level, "score": certification.score}
            if certification
            else None
        ),
    }


@router.get("/marketplace/{offering_slug}/examples/{artifact_id}/download")
def marketplace_example_download(
    offering_slug: str,
    artifact_id: str,
    db: Database,
    settings: AppSettings,
) -> dict[str, object]:
    row = db.execute(
        select(Offering, OfferingVersion)
        .join(OfferingVersion, Offering.latest_version_id == OfferingVersion.id)
        .where(
            or_(Offering.slug == offering_slug, Offering.id == offering_slug),
            Offering.status == "published",
            OfferingVersion.status == "published",
        )
    ).first()
    if row is None or artifact_id not in row[1].example_artifact_ids:
        raise HTTPException(status_code=404, detail="example_artifact_not_found")
    artifact = db.get(Artifact, artifact_id)
    if (
        artifact is None
        or artifact.owner_id != row[0].owner_id
        or artifact.task_id is not None
        or artifact.scan_status != "clean"
        or artifact.deleted_at is not None
        or artifact.storage_key is None
    ):
        raise HTTPException(status_code=404, detail="example_artifact_not_found")
    url = S3ArtifactStore(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_bucket,
        settings.s3_public_endpoint_url,
    ).signed_download(artifact.storage_key, settings.signed_url_ttl_seconds)
    return {"url": url, "expires_in": settings.signed_url_ttl_seconds}
