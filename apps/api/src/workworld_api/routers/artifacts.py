from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from workworld_api.config import Settings
from workworld_api.dependencies import AppSettings, CurrentUser, Database
from workworld_api.models import Artifact
from workworld_api.services.artifact_retention import ArtifactRetentionService
from workworld_api.services.artifacts import ArtifactError, ArtifactService
from workworld_api.services.clamav import ClamAVClient
from workworld_api.services.s3_store import S3ArtifactStore

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


class BeginUpload(BaseModel):
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
    direction: Literal["input", "output"]
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    task_id: str | None = None
    visibility: Literal["public", "applicants", "winner"] = "winner"


class CompleteUpload(BaseModel):
    parts: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)

    @field_validator("parts")
    @classmethod
    def valid_parts(cls, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        numbers: set[int] = set()
        for part in parts:
            if set(part) != {"PartNumber", "ETag"}:
                raise ValueError("multipart_part_fields_invalid")
            number = part["PartNumber"]
            etag = part["ETag"]
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 1 <= number <= 10_000
                or number in numbers
            ):
                raise ValueError("multipart_part_number_invalid")
            if not isinstance(etag, str) or not 1 <= len(etag) <= 512:
                raise ValueError("multipart_part_etag_invalid")
            numbers.add(number)
        return sorted(parts, key=lambda item: int(item["PartNumber"]))


def make_store(settings: Settings) -> S3ArtifactStore:
    return S3ArtifactStore(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_bucket,
        settings.s3_public_endpoint_url,
    )


def service(db: Database, settings: AppSettings) -> ArtifactService:
    return ArtifactService(
        db,
        settings,
        make_store(settings),
        ClamAVClient(settings.clamav_host, settings.clamav_port),
    )


def view(artifact: Artifact) -> dict[str, object]:
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "scan_status": artifact.scan_status,
        "metadata": artifact.metadata_json,
    }


@router.post("/uploads", status_code=201)
def begin_upload(
    body: BeginUpload, user: CurrentUser, db: Database, settings: AppSettings
) -> dict[str, object]:
    try:
        artifact = service(db, settings).begin(user, **body.model_dump())
        return {**view(artifact), "upload_id": artifact.multipart_upload_id}
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{artifact_id}/parts/{part_number}")
def sign_part(
    artifact_id: str,
    part_number: int,
    user: CurrentUser,
    db: Database,
    settings: AppSettings,
) -> dict[str, str]:
    try:
        return {"url": service(db, settings).signed_part(user, artifact_id, part_number)}
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{artifact_id}/complete")
def complete_upload(
    body: CompleteUpload,
    artifact_id: str,
    user: CurrentUser,
    db: Database,
    settings: AppSettings,
) -> dict[str, object]:
    try:
        return view(service(db, settings).complete(user, artifact_id, body.parts))
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{artifact_id}/download")
def download(
    artifact_id: str, user: CurrentUser, db: Database, settings: AppSettings
) -> dict[str, str]:
    try:
        return {"url": service(db, settings).download_url(user, artifact_id)}
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{artifact_id}")
def delete_artifact(
    artifact_id: str, user: CurrentUser, db: Database, settings: AppSettings
) -> dict[str, object]:
    try:
        artifact = ArtifactRetentionService(db, make_store(settings)).request_owner_deletion(
            user, artifact_id
        )
    except ArtifactError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": artifact.id, "deleted_at": artifact.deleted_at}
