from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.models import Artifact, User
from workworld_api.services.artifact_retention import (
    RETENTION_DAYS,
    ArtifactRetentionService,
    mark_settled,
)
from workworld_api.services.artifacts import ArtifactError
from workworld_api.services.s3_store import S3ArtifactStore


def test_settlement_starts_ninety_day_retention() -> None:
    @dataclass
    class Record:
        settled_at: datetime | None = None
        delete_after: datetime | None = None

    artifact = Record()
    settled_at = datetime(2026, 8, 10, tzinfo=UTC)
    mark_settled(artifact, settled_at)
    assert artifact.settled_at == settled_at
    assert (artifact.delete_after - settled_at).days == RETENTION_DAYS


def test_due_artifact_is_tombstoned_and_real_object_delete_is_requested() -> None:
    class Store:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete(self, key: str) -> bool:
            self.deleted.append(key)
            return True

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        owner = User(
            id="owner",
            email="owner@example.com",
            password_hash="x",
            role="user",
            email_verified=True,
            suspended=False,
            created_at=now,
        )
        artifact = Artifact(
            id="artifact_due",
            owner_id=owner.id,
            task_id=None,
            direction="input",
            kind="text",
            mime_type="text/plain",
            declared_mime_type="text/plain",
            original_name="due.txt",
            size_bytes=1,
            expected_size_bytes=1,
            sha256="0" * 64,
            expected_sha256="0" * 64,
            storage_key="artifacts/owner/due",
            scan_status="clean",
            metadata_json={},
            created_at=now,
            settled_at=now - timedelta(days=91),
            delete_after=now - timedelta(days=1),
        )
        db.add_all([owner, artifact])
        db.commit()
        store = Store()
        service = ArtifactRetentionService(db, store)  # type: ignore[arg-type]
        assert service.expire_due(now) == 1
        assert store.deleted == ["artifacts/owner/due"]
        assert artifact.deleted_at is not None
        assert artifact.deleted_at.replace(tzinfo=UTC) == now
        assert artifact.storage_key is None


def test_owner_cannot_delete_before_settlement() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        owner = User(
            id="owner",
            email="owner@example.com",
            password_hash="x",
            role="user",
            email_verified=True,
            suspended=False,
            created_at=now,
        )
        artifact = Artifact(
            id="artifact_locked",
            owner_id=owner.id,
            task_id=None,
            direction="input",
            kind="text",
            mime_type="text/plain",
            declared_mime_type="text/plain",
            original_name="locked.txt",
            size_bytes=1,
            expected_size_bytes=1,
            sha256="0" * 64,
            expected_sha256="0" * 64,
            storage_key="artifacts/owner/locked",
            scan_status="clean",
            metadata_json={},
            created_at=now,
        )
        db.add_all([owner, artifact])
        db.commit()
        with pytest.raises(ArtifactError, match="artifact_locked_until_settlement"):
            ArtifactRetentionService(
                db, object.__new__(S3ArtifactStore)
            ).request_owner_deletion(owner, artifact.id)
