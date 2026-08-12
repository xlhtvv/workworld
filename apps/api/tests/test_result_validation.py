from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.database import Base
from workworld_api.market_models import Agent
from workworld_api.models import Artifact, User
from workworld_api.services.result_validation import ResultValidationError, validate_result
from workworld_api.task_models import Run, Task


def context(
    db: Session, schema_id: str, task_input: dict[str, object]
) -> tuple[Run, User, User]:
    now = datetime.now(UTC)
    publisher = User(
        id="user_publisher",
        email="publisher@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=now,
    )
    provider = User(
        id="user_provider",
        email="provider@example.com",
        password_hash="x",
        role="user",
        email_verified=True,
        suspended=False,
        created_at=now,
    )
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
        publisher_id=publisher.id,
        schema_id=schema_id,
        schema_version="1.0",
        title="Task",
        public_summary="Task",
        input_json=task_input,
        field_visibility={},
        difficulty="simple",
        acceptance_rules={},
        budget_tokens=1000,
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
        schema_version_id=f"{schema_id}@1.0",
        last_agent_sequence=0,
        next_event_sequence=1,
        clarification_rounds=0,
        rework_count=0,
        offer_expires_at=now,
        completion_deadline=now,
        created_at=now,
    )
    db.add_all([publisher, provider, agent, task, run])
    db.commit()
    return run, publisher, provider


def artifact(
    db: Session,
    owner: User,
    artifact_id: str,
    direction: str,
    kind: str,
    metadata: dict[str, object],
) -> Artifact:
    row = Artifact(
        id=artifact_id,
        owner_id=owner.id,
        task_id="task_1",
        direction=direction,
        kind=kind,
        mime_type="application/octet-stream",
        declared_mime_type="application/octet-stream",
        original_name="fixture.bin",
        size_bytes=1,
        expected_size_bytes=1,
        sha256="0" * 64,
        expected_sha256="0" * 64,
        storage_key=f"artifacts/{artifact_id}",
        scan_status="clean",
        metadata_json=metadata,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    return row


def test_text_length_and_json_postconditions_are_platform_validated() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, _ = context(
            db,
            "text.summarize",
            {"text": "source", "max_characters": 50, "difficulty": "simple"},
        )
        with pytest.raises(ResultValidationError, match="hard_validation_failed:max_characters"):
            validate_result(db, run, {"output": {"summary": "x" * 51}})
        validate_result(db, run, {"output": {"summary": "x" * 50}})

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, _ = context(
            db,
            "json.transform",
            {
                "document": {"a": 1, "nested": {"keep": True}},
                "operations": [
                    {"op": "set", "path": "nested.value", "value": 2},
                    {"op": "remove", "path": "a"},
                ],
                "difficulty": "simple",
            },
        )
        with pytest.raises(
            ResultValidationError, match="hard_validation_failed:operation_postconditions"
        ):
            validate_result(db, run, {"output": {"document": {"a": 1}}})
        validate_result(
            db, run, {"output": {"document": {"nested": {"keep": True, "value": 2}}}}
        )


def test_image_dimensions_and_repository_findings_are_grounded_in_artifacts() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, publisher, provider = context(
            db,
            "image.edit",
            {"instruction": "border", "preserve_dimensions": True, "difficulty": "simple"},
        )
        artifact(db, publisher, "artifact_input", "input", "image", {"width": 20, "height": 10})
        output = artifact(
            db, provider, "artifact_output", "output", "image", {"width": 21, "height": 10}
        )
        with pytest.raises(ResultValidationError, match="hard_validation_failed:image_decodable"):
            validate_result(db, run, {"output": {"artifact_id": output.id}})
        output.metadata_json = {"width": 20, "height": 10}
        db.commit()
        validate_result(db, run, {"output": {"artifact_id": output.id}})

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, publisher, _ = context(
            db,
            "repository.code-review",
            {"focus": ["correctness"], "base_commit": None, "difficulty": "simple"},
        )
        artifact(
            db,
            publisher,
            "artifact_repository",
            "input",
            "repository_snapshot",
            {"files": [{"path": "src/app.py", "line_count": 10}]},
        )
        invalid = {
            "findings": [
                {"severity": "high", "path": "src/app.py", "line": 11, "summary": "Bug"}
            ]
        }
        with pytest.raises(ResultValidationError, match="hard_validation_failed:line_bounds"):
            validate_result(db, run, {"output": invalid})
        valid = {
            "findings": [
                {"severity": "high", "path": "src/app.py", "line": 10, "summary": "Bug"}
            ]
        }
        validate_result(db, run, {"output": valid})


def test_language_answer_count_and_media_timestamps_are_hard_failures() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, provider = context(
            db,
            "document.translate",
            {"target_language": "zh", "preserve_layout": True, "difficulty": "simple"},
        )
        output = artifact(db, provider, "artifact_translation", "output", "document", {})
        with pytest.raises(ResultValidationError, match="hard_validation_failed:target_language"):
            validate_result(
                db, run, {"output": {"artifact_id": output.id, "language": "en"}}
            )
        validate_result(db, run, {"output": {"artifact_id": output.id, "language": "ZH"}})

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, _ = context(
            db,
            "spreadsheet.analyze",
            {"questions": ["one", "two"], "include_charts": False, "difficulty": "simple"},
        )
        with pytest.raises(ResultValidationError, match="hard_validation_failed:answer_count"):
            validate_result(db, run, {"output": {"answers": ["one"]}})
        validate_result(db, run, {"output": {"answers": ["one", "two"]}})

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, publisher, _ = context(
            db,
            "audio.transcribe",
            {"language_hint": None, "timestamps": "segment", "difficulty": "simple"},
        )
        artifact(
            db, publisher, "artifact_audio", "input", "audio", {"duration_seconds": 3.0}
        )
        invalid = {
            "text": "speech",
            "language": "en",
            "segments": [{"start": 0, "end": 4, "text": "speech"}],
        }
        with pytest.raises(ResultValidationError, match="hard_validation_failed:timestamp_bounds"):
            validate_result(db, run, {"output": invalid})
        valid = {
            "text": "speech",
            "language": "en",
            "segments": [{"start": 0, "end": 3, "text": "speech"}],
        }
        validate_result(db, run, {"output": valid})


def test_generated_image_dimensions_and_archive_metadata_are_verified() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, provider = context(
            db,
            "image.generate",
            {
                "prompt": "a square",
                "width": 512,
                "height": 512,
                "format": "png",
                "difficulty": "simple",
            },
        )
        image = artifact(
            db, provider, "artifact_image", "output", "image", {"width": 1024, "height": 512}
        )
        with pytest.raises(ResultValidationError, match="hard_validation_failed:image_dimensions"):
            validate_result(db, run, {"output": {"artifact_id": image.id}})
        image.metadata_json = {"width": 512, "height": 512}
        db.commit()
        validate_result(db, run, {"output": {"artifact_id": image.id}})

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run, _, provider = context(
            db,
            "archive.process",
            {"instruction": "list", "output_format": "archive", "difficulty": "simple"},
        )
        archive = artifact(db, provider, "artifact_archive", "output", "archive", {})
        with pytest.raises(ResultValidationError, match="hard_validation_failed:archive_limits"):
            validate_result(
                db, run, {"output": {"manifest": ["one.txt"], "artifact_id": archive.id}}
            )
        archive.metadata_json = {
            "file_count": 1,
            "uncompressed_size_bytes": 3,
            "nested_depth": 0,
        }
        db.commit()
        validate_result(
            db, run, {"output": {"manifest": ["one.txt"], "artifact_id": archive.id}}
        )
