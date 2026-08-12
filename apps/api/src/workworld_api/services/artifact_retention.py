from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from workworld_api.models import Artifact, User
from workworld_api.services.artifact_errors import ArtifactError
from workworld_api.services.s3_store import S3ArtifactStore

RETENTION_DAYS = 90


class RetentionRecord(Protocol):
    settled_at: datetime | None
    delete_after: datetime | None


def mark_settled(artifact: RetentionRecord, settled_at: datetime) -> None:
    artifact.settled_at = settled_at
    artifact.delete_after = settled_at + timedelta(days=RETENTION_DAYS)


class ArtifactRetentionService:
    def __init__(self, db: Session, store: S3ArtifactStore) -> None:
        self.db = db
        self.store = store

    def request_owner_deletion(self, owner: User, artifact_id: str) -> Artifact:
        artifact = self.db.get(Artifact, artifact_id)
        if artifact is None or artifact.owner_id != owner.id:
            raise ArtifactError("artifact_not_available")
        if artifact.settled_at is None:
            raise ArtifactError("artifact_locked_until_settlement")
        self._tombstone(artifact, datetime.now(UTC))
        return artifact

    def expire_due(self, now: datetime, limit: int = 100) -> int:
        due = self.db.scalars(
            select(Artifact)
            .where(
                Artifact.storage_key.is_not(None),
                or_(Artifact.deleted_at.is_not(None), Artifact.delete_after <= now),
            )
            .limit(limit)
        ).all()
        for artifact in due:
            self._tombstone(artifact, now)
        return len(due)

    def _tombstone(self, artifact: Artifact, now: datetime) -> None:
        if artifact.deleted_at is None:
            artifact.deleted_at = now
            self.db.commit()
        if artifact.storage_key is not None and self.store.delete(artifact.storage_key):
            artifact.storage_key = None
            artifact.multipart_upload_id = None
            self.db.commit()
