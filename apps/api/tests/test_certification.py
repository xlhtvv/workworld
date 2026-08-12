import hashlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.market_models import Agent, AgentEndpoint, Offering, OfferingVersion
from workworld_api.models import Artifact, ScanStatus, User
from workworld_api.services.certification import (
    REQUIRED_CHECKS,
    PushCertificationService,
    certify_transcript,
)
from workworld_api.services.endpoint_security import ValidatedEndpoint
from workworld_api.task_models import Run

assert Run.__tablename__ == "runs"


def records(db: Session) -> OfferingVersion:
    now = datetime.now(UTC)
    db.add(
        User(
            id="user_1",
            email="one@example.com",
            password_hash="x",
            role="user",
            email_verified=True,
            suspended=False,
            created_at=now,
        )
    )
    db.add(
        Agent(id="agent_1", owner_id="user_1", name="A", slug="a", status="active", created_at=now)
    )
    db.add(
        Offering(
            id="offering_1",
            agent_id="agent_1",
            owner_id="user_1",
            slug="summary",
            status="draft",
            latest_version_id="offering_1_v1",
            created_at=now,
        )
    )
    version = OfferingVersion(
        id="offering_1_v1",
        offering_id="offering_1",
        version=1,
        schema_id="text.summarize",
        schema_version="1.0",
        name_i18n={"en": "Summary", "zh": "摘要"},
        description_i18n={"en": "Summary", "zh": "摘要"},
        capabilities=[],
        risk_disclosure="third party",
        output_license="publisher-use",
        sla_seconds=60,
        input_limits={},
        estimated_tokens_min=1,
        estimated_tokens_max=10,
        estimated_seconds_min=1,
        estimated_seconds_max=10,
        auto_apply_policy={},
        status="draft",
        content_sha256="0" * 64,
        created_at=now,
    )
    db.add(version)
    db.commit()
    return version


def test_certification_requires_every_protocol_scenario_and_valid_output() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        version = records(db)
        incomplete = certify_transcript(
            db,
            version.id,
            [{"check": "handshake", "passed": True}],
            {"text": "long input", "difficulty": "simple"},
            {"summary": "short"},
        )
        assert incomplete.status == "failed"
        transcript = [
            {"check": name, "passed": True}
            for name in REQUIRED_CHECKS
            if name != "output_validation"
        ]
        passed = certify_transcript(
            db,
            version.id,
            transcript,
            {"text": "long input", "difficulty": "simple"},
            {"summary": "short"},
        )
        assert passed.status == "passed"
        assert passed.level == "capability_verified"
        assert passed.score == 100
        invalid = certify_transcript(
            db,
            version.id,
            transcript,
            {"text": "long input", "difficulty": "simple"},
            {"wrong": "shape"},
        )
        assert invalid.status == "failed"


@pytest.mark.parametrize("endpoint_type", ["pull", "push"])
def test_certification_uses_server_challenges_and_clean_artifact(
    endpoint_type: str,
) -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        version = records(db)
        db.add(
            AgentEndpoint(
                id="endpoint_1",
                agent_id="agent_1",
                endpoint_type=endpoint_type,
                url="https://provider.example/workworld" if endpoint_type == "push" else None,
                status="verified",
                resolved_addresses=["8.8.8.8"],
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

        def sender(
            _endpoint: ValidatedEndpoint, payload: object, _secret: str
        ) -> tuple[int, bytes]:
            assert isinstance(payload, dict)
            artifact_content = payload["artifact_challenge"]["content_utf8"]
            artifact_hash = hashlib.sha256(artifact_content.encode()).hexdigest()
            db.add(
                Artifact(
                    id="artifact_certification",
                    owner_id="user_1",
                    task_id=None,
                    direction="output",
                    kind="generic_file",
                    mime_type="text/plain",
                    original_name="certification.txt",
                    size_bytes=len(artifact_content),
                    sha256=artifact_hash,
                    storage_key="clean/certification.txt",
                    expected_size_bytes=len(artifact_content),
                    expected_sha256=artifact_hash,
                    declared_mime_type="text/plain",
                    scan_status=ScanStatus.CLEAN,
                    metadata_json={},
                    created_at=datetime.now(UTC),
                )
            )
            db.flush()
            response = {
                "certification_id": payload["certification_id"],
                "results": [
                    {"name": item["name"], "challenge": item["challenge"], "passed": True}
                    for item in payload["scenarios"]
                ],
                "sample_output": {"summary": "A short certification result."},
                "artifact_id": "artifact_certification",
            }
            return 200, json.dumps(response).encode()

        owner = db.get(User, "user_1")
        assert owner is not None
        certification = PushCertificationService(
            db,
            Settings(),
            endpoint_type=endpoint_type,
            validator=lambda url: ValidatedEndpoint(
                url, "provider.example", 443, frozenset({"8.8.8.8"})
            ),
            sender=sender,
        ).run(owner, version.id)
        assert certification.status == "passed"
        assert {item["name"] for item in certification.checks_json} == REQUIRED_CHECKS


def test_push_certification_rejects_replayed_or_missing_challenges() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        version = records(db)
        db.add(
            AgentEndpoint(
                id="endpoint_1",
                agent_id="agent_1",
                endpoint_type="push",
                url="https://provider.example/workworld",
                status="verified",
                resolved_addresses=["8.8.8.8"],
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

        def replay(
            _endpoint: ValidatedEndpoint, payload: object, _secret: str
        ) -> tuple[int, bytes]:
            assert isinstance(payload, dict)
            return 200, json.dumps(
                {
                    "certification_id": payload["certification_id"],
                    "results": [
                        {"name": name, "challenge": "old", "passed": True}
                        for name in REQUIRED_CHECKS
                    ],
                    "sample_output": {"summary": "Valid shape is insufficient."},
                }
            ).encode()

        owner = db.get(User, "user_1")
        assert owner is not None
        certification = PushCertificationService(
            db,
            Settings(),
            validator=lambda url: ValidatedEndpoint(
                url, "provider.example", 443, frozenset({"8.8.8.8"})
            ),
            sender=replay,
        ).run(owner, version.id)
        assert certification.status == "failed"
        assert certification.level == "protocol_verified"
