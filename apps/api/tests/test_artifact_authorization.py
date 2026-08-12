from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.market_models import Agent
from workworld_api.models import Artifact, User
from workworld_api.services.artifacts import ArtifactError, ArtifactService
from workworld_api.services.clamav import ClamAVClient
from workworld_api.services.s3_store import S3ArtifactStore
from workworld_api.task_models import Application, Run, Task, TaskArtifact


def user(user_id: str, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="not-used",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=datetime.now(UTC),
    )


def test_cross_tenant_and_pending_artifact_downloads_are_denied() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    settings = Settings()
    with Session(engine) as db:
        owner = user("user_owner", "owner@example.com")
        provider = user("user_provider", "provider@example.com")
        stranger = user("user_stranger", "stranger@example.com")
        now = datetime.now(UTC)
        agent = Agent(
            id="agent_1",
            owner_id=provider.id,
            name="Agent",
            slug="agent",
            status="active",
            created_at=now,
        )
        task = Task(
            id="task_1",
            publisher_id=owner.id,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Task",
            public_summary="Task",
            input_json={"text": "private", "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={},
            budget_tokens=100,
            completion_deadline=now,
            assignment_mode="recommended",
            status="candidate_selected",
            created_at=now,
        )
        run = Run(
            id="run_1",
            task_id=task.id,
            attempt=1,
            offering_version_id="offering_version_1",
            agent_id=agent.id,
            state="running",
            protocol_version="1.0",
            schema_version_id="text.summarize@1.0",
            last_agent_sequence=0,
            next_event_sequence=1,
            clarification_rounds=0,
            rework_count=0,
            offer_expires_at=now,
            completion_deadline=now,
            created_at=now,
        )
        db.add_all([owner, provider, stranger, agent, task, run])
        artifact = Artifact(
            id="artifact_private",
            owner_id=owner.id,
            task_id=task.id,
            direction="input",
            kind="json",
            mime_type="application/json",
            declared_mime_type="application/json",
            original_name="private.json",
            size_bytes=2,
            expected_size_bytes=2,
            sha256="0" * 64,
            expected_sha256="0" * 64,
            storage_key="artifacts/user_owner/artifact_private",
            multipart_upload_id=None,
            scan_status="clean",
            metadata_json={"node_count": 1},
            created_at=datetime.now(UTC),
        )
        relation = TaskArtifact(
            id="task_artifact_private",
            task_id=task.id,
            artifact_id=artifact.id,
            direction="input",
            visibility="winner",
            attached_at=now,
        )
        db.add_all([artifact, relation])
        db.commit()
        service = ArtifactService(
            db,
            settings,
            S3ArtifactStore(
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            ),
            ClamAVClient(settings.clamav_host, settings.clamav_port),
        )
        with pytest.raises(ArtifactError, match="artifact_not_available"):
            service.download_url(stranger, artifact.id)
        assert service.download_url(provider, artifact.id).startswith("http")
        artifact.scan_status = "pending"
        db.commit()
        with pytest.raises(ArtifactError, match="artifact_not_available"):
            service.download_url(owner, artifact.id)


def test_input_artifact_visibility_distinguishes_applicants_and_public_users() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    settings = Settings()
    with Session(engine) as db:
        publisher = user("user_publisher", "publisher@example.com")
        applicant = user("user_applicant", "applicant@example.com")
        stranger = user("user_stranger", "stranger@example.com")
        now = datetime.now(UTC)
        task = Task(
            id="task_visibility",
            publisher_id=publisher.id,
            schema_id="text.summarize",
            schema_version="1.0",
            title="Task",
            public_summary="Task",
            input_json={"text": "private", "difficulty": "simple"},
            field_visibility={},
            difficulty="simple",
            acceptance_rules={},
            budget_tokens=100,
            completion_deadline=now,
            assignment_mode="open_call",
            status="open",
            created_at=now,
        )
        application = Application(
            id="application_1",
            task_id=task.id,
            offering_version_id="offering_version_1",
            provider_id=applicant.id,
            estimated_tokens_min=1,
            estimated_tokens_max=2,
            estimated_completion_seconds=60,
            message="I can help",
            valid_until=now,
            status="submitted",
            created_at=now,
        )
        artifacts = []
        relations = []
        for visibility in ("applicants", "public"):
            artifact = Artifact(
                id=f"artifact_{visibility}",
                owner_id=publisher.id,
                task_id=task.id,
                direction="input",
                kind="json",
                mime_type="application/json",
                declared_mime_type="application/json",
                original_name=f"{visibility}.json",
                size_bytes=2,
                expected_size_bytes=2,
                sha256="0" * 64,
                expected_sha256="0" * 64,
                storage_key=f"artifacts/{publisher.id}/{visibility}",
                multipart_upload_id=None,
                scan_status="clean",
                metadata_json={},
                created_at=now,
            )
            artifacts.append(artifact)
            relations.append(
                TaskArtifact(
                    id=f"task_artifact_{visibility}",
                    task_id=task.id,
                    artifact_id=artifact.id,
                    direction="input",
                    visibility=visibility,
                    attached_at=now,
                )
            )
        db.add_all([publisher, applicant, stranger, task, application, *artifacts, *relations])
        db.commit()
        service = ArtifactService(
            db,
            settings,
            S3ArtifactStore(
                settings.s3_endpoint_url,
                settings.s3_access_key,
                settings.s3_secret_key,
                settings.s3_bucket,
            ),
            ClamAVClient(settings.clamav_host, settings.clamav_port),
        )
        assert service.download_url(applicant, "artifact_applicants").startswith("http")
        with pytest.raises(ArtifactError, match="artifact_not_available"):
            service.download_url(stranger, "artifact_applicants")
        assert service.download_url(stranger, "artifact_public").startswith("http")
