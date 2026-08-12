from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.ids import new_id as _id
from workworld_api.market_models import Agent
from workworld_api.models import (
    Artifact,
    ArtifactMeasurement,
    ArtifactScanResult,
    ScanStatus,
    User,
)
from workworld_api.services.artifact_errors import ArtifactError as ArtifactError
from workworld_api.services.artifact_safety import (
    CHUNK_SIZE,
    InspectedArtifact,
    UnsafeArtifact,
    inspect_stream,
)
from workworld_api.services.clamav import ClamAVClient, ClamAVError
from workworld_api.services.moderation import ModerationBlocked, ModerationService
from workworld_api.services.s3_store import S3ArtifactStore
from workworld_api.task_models import Application, Run, Task, TaskArtifact


class ArtifactService:
    def __init__(
        self, db: Session, settings: Settings, store: S3ArtifactStore, scanner: ClamAVClient
    ) -> None:
        self.db = db
        self.settings = settings
        self.store = store
        self.scanner = scanner

    def begin(
        self,
        owner: User,
        *,
        original_name: str,
        kind: str,
        direction: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        task_id: str | None,
        visibility: str = "winner",
    ) -> Artifact:
        if size_bytes <= 0 or size_bytes > self.settings.artifact_max_bytes:
            raise ArtifactError("artifact_size_limit")
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ArtifactError("invalid_sha256")
        if task_id is not None:
            self._authorize_attachment(owner, task_id, direction)
        if direction == "output" and visibility != "winner":
            raise ArtifactError("output_artifact_visibility_invalid")
        artifact_id = _id("artifact")
        quarantine_key = f"quarantine/{owner.id}/{artifact_id}"
        upload_id = self.store.begin_multipart(quarantine_key, mime_type)
        artifact = Artifact(
            id=artifact_id,
            owner_id=owner.id,
            task_id=task_id,
            direction=direction,
            kind=kind,
            mime_type=mime_type,
            declared_mime_type=mime_type,
            original_name=original_name,
            size_bytes=size_bytes,
            expected_size_bytes=size_bytes,
            sha256=None,
            expected_sha256=sha256,
            storage_key=quarantine_key,
            multipart_upload_id=upload_id,
            scan_status=ScanStatus.PENDING,
            metadata_json={},
            created_at=datetime.now(UTC),
        )
        self.db.add(artifact)
        if task_id is not None:
            self.db.add(
                TaskArtifact(
                    id=_id("task_artifact"),
                    task_id=task_id,
                    artifact_id=artifact.id,
                    direction=direction,
                    visibility=visibility,
                    attached_at=artifact.created_at,
                )
            )
        self.db.commit()
        return artifact

    def signed_part(self, owner: User, artifact_id: str, part_number: int) -> str:
        artifact = self._owned_pending(owner, artifact_id)
        assert artifact.storage_key is not None
        assert artifact.multipart_upload_id is not None
        return self.store.signed_part(
            artifact.storage_key,
            artifact.multipart_upload_id,
            part_number,
            self.settings.signed_url_ttl_seconds,
        )

    def complete(self, owner: User, artifact_id: str, parts: list[dict[str, Any]]) -> Artifact:
        artifact = self._owned_pending(owner, artifact_id)
        assert artifact.storage_key is not None
        assert artifact.multipart_upload_id is not None
        try:
            confirmed_parts = parts or self.store.uploaded_parts(
                artifact.storage_key, artifact.multipart_upload_id
            )
        except ValueError as exc:
            raise ArtifactError(str(exc)) from exc
        self.store.complete(
            artifact.storage_key, artifact.multipart_upload_id, confirmed_parts
        )
        inspected: InspectedArtifact | None = None
        try:
            inspected = inspect_stream(
                self.store.chunks(artifact.storage_key),
                artifact.original_name,
                self.settings.artifact_max_bytes,
                artifact.kind,
            )
            if inspected.size_bytes != artifact.expected_size_bytes:
                raise UnsafeArtifact("size_mismatch")
            if inspected.sha256 != artifact.expected_sha256:
                raise UnsafeArtifact("sha256_mismatch")
            if inspected.mime_type != artifact.declared_mime_type:
                raise UnsafeArtifact("declared_mime_mismatch")
            inspected.file.seek(0)
            verdict = self.scanner.scan(iter(lambda: inspected.file.read(CHUNK_SIZE), b""))
            scanner_version = self.scanner.version()
        except (UnsafeArtifact, ClamAVError) as exc:
            if inspected is not None:
                inspected.file.close()
            artifact.scan_status = ScanStatus.REJECTED
            self._scan_record(artifact, ScanStatus.REJECTED, str(exc), None)
            self.db.commit()
            raise ArtifactError(str(exc)) from exc
        if not verdict.clean:
            inspected.file.close()
            artifact.scan_status = ScanStatus.INFECTED
            self._scan_record(artifact, ScanStatus.INFECTED, verdict.signature, None)
            self.db.commit()
            raise ArtifactError("malware_detected")
        try:
            if inspected.mime_type.startswith("text/"):
                inspected.file.seek(0)
                ModerationService(self.db, self.settings).check_text(
                    "artifact", artifact.id, inspected.file.read().decode("utf-8")
                )
            elif inspected.mime_type.startswith("image/"):
                inspected.file.seek(0)
                ModerationService(self.db, self.settings).check_image(
                    "artifact", artifact.id, inspected.file.read()
                )
            elif inspected.mime_type.startswith("audio/"):
                inspected.file.seek(0)
                ModerationService(self.db, self.settings).check_audio(
                    "artifact",
                    artifact.id,
                    inspected.file.read(),
                    artifact.original_name,
                    inspected.mime_type,
                )
            elif inspected.mime_type.startswith("video/"):
                inspected.file.seek(0)
                ModerationService(self.db, self.settings).check_video(
                    "artifact",
                    artifact.id,
                    inspected.file.read(),
                    float(inspected.metadata.get("duration_seconds", 0)),
                )
        except ModerationBlocked as exc:
            inspected.file.close()
            artifact.scan_status = ScanStatus.REJECTED
            self._scan_record(
                artifact,
                ScanStatus.REJECTED,
                ",".join(exc.categories),
                self.settings.openai_moderation_model
                if self.settings.moderation_mode == "openai"
                else "workworld_text_rules_v1",
                scanner="content_moderation",
            )
            self.db.commit()
            raise ArtifactError(str(exc)) from exc
        target_key = f"artifacts/{owner.id}/{artifact.id}"
        source_key = artifact.storage_key
        self.store.copy(source_key, target_key)
        artifact.storage_key = target_key
        artifact.multipart_upload_id = None
        artifact.sha256 = inspected.sha256
        artifact.size_bytes = inspected.size_bytes
        artifact.mime_type = inspected.mime_type
        artifact.metadata_json = inspected.metadata
        artifact.scan_status = ScanStatus.CLEAN
        self._scan_record(artifact, ScanStatus.CLEAN, None, scanner_version)
        self.db.add(
            ArtifactMeasurement(
                id=_id("measurement"),
                artifact_id=artifact.id,
                strategy_version="artifact_metadata_v1",
                values_json=inspected.metadata,
                measured_at=datetime.now(UTC),
            )
        )
        self.db.commit()
        self.store.delete(source_key)
        inspected.file.close()
        return artifact

    def download_url(self, owner: User, artifact_id: str) -> str:
        artifact = self.db.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.scan_status != ScanStatus.CLEAN
            or artifact.deleted_at is not None
            or artifact.storage_key is None
            or not self._can_download(owner, artifact)
        ):
            raise ArtifactError("artifact_not_available")
        return self.store.signed_download(
            artifact.storage_key, self.settings.signed_url_ttl_seconds
        )

    def _authorize_attachment(self, owner: User, task_id: str, direction: str) -> None:
        task = self.db.get(Task, task_id)
        if task is None:
            raise ArtifactError("task_not_found")
        if direction == "input" and task.publisher_id == owner.id:
            return
        if direction == "output" and self._is_winning_provider(owner.id, task_id):
            return
        raise ArtifactError("artifact_task_access_denied")

    def _can_download(self, user: User, artifact: Artifact) -> bool:
        if artifact.owner_id == user.id:
            return True
        if artifact.task_id is None:
            return False
        task = self.db.get(Task, artifact.task_id)
        if task is None:
            return False
        if artifact.direction == "output" and task.publisher_id == user.id:
            return True
        if artifact.direction != "input":
            return False
        relation = self.db.scalar(
            select(TaskArtifact).where(
                TaskArtifact.task_id == artifact.task_id,
                TaskArtifact.artifact_id == artifact.id,
                TaskArtifact.direction == "input",
            )
        )
        if relation is None:
            return False
        if relation.visibility == "public":
            return True
        if self._is_winning_provider(user.id, artifact.task_id):
            return True
        return relation.visibility == "applicants" and self._is_applicant(
            user.id, artifact.task_id
        )

    def _is_applicant(self, user_id: str, task_id: str) -> bool:
        return (
            self.db.scalar(
                select(Application.id)
                .where(
                    Application.task_id == task_id,
                    Application.provider_id == user_id,
                    Application.status.not_in(["withdrawn", "rejected"]),
                )
                .limit(1)
            )
            is not None
        )

    def _is_winning_provider(self, user_id: str, task_id: str) -> bool:
        return (
            self.db.scalar(
                select(Run.id)
                .join(Agent, Agent.id == Run.agent_id)
                .where(
                    Run.task_id == task_id,
                    Agent.owner_id == user_id,
                    Run.state.not_in(["cancelled", "failed", "timed_out"]),
                )
                .limit(1)
            )
            is not None
        )

    def _owned_pending(self, owner: User, artifact_id: str) -> Artifact:
        artifact = self.db.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.owner_id != owner.id
            or artifact.scan_status != ScanStatus.PENDING
        ):
            raise ArtifactError("artifact_not_pending")
        return artifact

    def _scan_record(
        self,
        artifact: Artifact,
        status: str,
        signature: str | None,
        version: str | None,
        *,
        scanner: str = "clamav",
    ) -> None:
        self.db.add(
            ArtifactScanResult(
                id=_id("scan"),
                artifact_id=artifact.id,
                scanner=scanner,
                scanner_version=version,
                status=status,
                signature=signature,
                scanned_at=datetime.now(UTC),
            )
        )
