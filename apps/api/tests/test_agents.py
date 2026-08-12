from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import OfferingCertification
from workworld_api.models import Artifact, User
from workworld_api.services.agents import AgentError, AgentService, OfferingService
from workworld_api.services.certification import REQUIRED_CHECKS
from workworld_api.services.endpoint_security import ValidatedEndpoint
from workworld_api.task_models import Run

assert Run.__tablename__ == "runs"


def account(user_id: str) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        password_hash="unused",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=datetime.now(UTC),
    )


def offering_definition() -> dict[str, object]:
    return {
        "schema_id": "text.summarize",
        "schema_version": "1.0",
        "name_i18n": {"en": "Summary", "zh": "摘要"},
        "description_i18n": {"en": "Summarizes", "zh": "生成摘要"},
        "capabilities": ["concise"],
        "risk_disclosure": "Provider may use a third-party model.",
        "output_license": "task-publisher-use",
        "sla_seconds": 600,
        "input_limits": {"max_characters": 500000},
        "estimated_tokens_min": 100,
        "estimated_tokens_max": 1000,
        "estimated_seconds_min": 5,
        "estimated_seconds_max": 300,
    }


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def endpoint_validator(url: str) -> ValidatedEndpoint:
    return ValidatedEndpoint(url, "provider.example", 443, frozenset({"8.8.8.8"}))


def echo_challenge(endpoint: ValidatedEndpoint, challenge: str) -> None:
    assert endpoint.host == "provider.example"
    assert len(challenge) > 20


def test_agent_credentials_are_one_time_secrets_rotatable_and_tenant_scoped(db: Session) -> None:
    owner = account("user_owner")
    stranger = account("user_stranger")
    db.add_all([owner, stranger])
    db.commit()
    service = AgentService(db, endpoint_validator, echo_challenge)
    agent = service.create(owner, "Text Agent")
    credential, raw = service.issue_credential(owner, agent.id)
    assert raw.startswith(f"wwa_{credential.key_prefix}.")
    assert raw not in credential.secret_hash
    assert service.authenticate(raw).id == agent.id
    with pytest.raises(AgentError, match="agent_not_found"):
        service.issue_credential(stranger, agent.id)
    service.revoke_credential(owner, credential.id)
    with pytest.raises(AgentError, match="invalid_agent_credential"):
        service.authenticate(raw)


def test_agent_public_name_is_moderated(db: Session) -> None:
    owner = account("user_owner")
    db.add(owner)
    db.commit()
    with pytest.raises(AgentError, match="content_blocked:contact_email"):
        AgentService(db, endpoint_validator, echo_challenge).create(
            owner, "Contact outside@example.com"
        )


def test_push_challenge_capacity_and_certification_gate(db: Session) -> None:
    owner = account("user_owner")
    db.add(owner)
    db.commit()
    agents = AgentService(db, endpoint_validator, echo_challenge)
    agent = agents.create(owner, "Push Agent")
    endpoint = agents.register_push_endpoint(owner, agent.id, "https://provider.example/workworld")
    assert endpoint.status == "verified"
    with pytest.raises(AgentError, match="active_runs_exceed_capacity"):
        agents.capacity(
            agent,
            status="online",
            max_concurrent_runs=1,
            active_runs=2,
            queue_capacity=0,
            estimated_wait_seconds=0,
            supported_offering_versions=[],
        )

    now = datetime.now(UTC)
    example = Artifact(
        id="artifact_example",
        owner_id=owner.id,
        task_id=None,
        direction="output",
        kind="text",
        mime_type="text/plain",
        declared_mime_type="text/plain",
        original_name="example.txt",
        size_bytes=7,
        expected_size_bytes=7,
        sha256="0" * 64,
        expected_sha256="0" * 64,
        storage_key="artifacts/user_owner/artifact_example",
        scan_status="clean",
        metadata_json={"character_count": 7},
        created_at=now,
    )
    db.add(example)
    db.commit()
    definition = offering_definition()
    definition["example_artifact_ids"] = [example.id]
    offerings = OfferingService(db)
    offering, first = offerings.create_version(owner, agent.id, "summary", definition)
    assert first.example_artifact_ids == [example.id]
    with pytest.raises(AgentError, match="offering_not_certified"):
        offerings.publish(owner, first.id)
    db.add(
        OfferingCertification(
            id="certification_1",
            offering_version_id=first.id,
            test_suite_version="1.0",
            status="passed",
            level="capability_verified",
            checks_json=[{"name": name, "passed": True} for name in REQUIRED_CHECKS],
            input_hash="1" * 64,
            output_hash="2" * 64,
            score=90,
            log_hash="3" * 64,
            started_at=now,
            completed_at=now,
        )
    )
    db.commit()
    assert offerings.publish(owner, first.id).status == "published"
    first.risk_disclosure = "silently changed"
    with pytest.raises(ValueError, match="published_offering_version_is_immutable"):
        db.commit()
    db.rollback()
    certification = db.get(OfferingCertification, "certification_1")
    assert certification is not None
    certification.score = 1
    with pytest.raises(ValueError, match="offering_certification_is_immutable"):
        db.commit()
    db.rollback()
    _, second = offerings.create_version(
        owner, agent.id, "summary", offering_definition(), offering.id
    )
    assert second.version == 2
    assert second.status == "draft"

    invalid = offering_definition()
    invalid["example_artifact_ids"] = ["artifact_missing"]
    with pytest.raises(AgentError, match="offering_example_artifact_invalid"):
        offerings.create_version(owner, agent.id, "invalid-example", invalid)
