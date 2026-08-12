import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from workworld_sdk.protocol import PROTOCOL_EVENT_TYPES

SCHEMA = json.loads(Path("schemas/protocol/envelope.schema.json").read_text())
VALID_MESSAGE = {
    "protocol_version": "1.0",
    "message_id": "00000000-0000-4000-8000-000000000001",
    "idempotency_key": "run_1:progress:1",
    "timestamp": "2026-08-10T12:00:00Z",
    "agent_id": "agent_123",
    "run_id": "run_123",
    "type": "task.progress",
    "sequence": 1,
    "payload": {"percent": 10},
}


def validate(message: dict[str, object]) -> None:
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(message)


def test_valid_protocol_message() -> None:
    validate(VALID_MESSAGE)


def test_python_sdk_event_types_match_the_protocol_schema() -> None:
    assert frozenset(SCHEMA["properties"]["type"]["enum"]) == PROTOCOL_EVENT_TYPES


@pytest.mark.parametrize(
    ("field", "value"),
    [("protocol_version", "2.0"), ("sequence", 0), ("type", "task.unknown")],
)
def test_invalid_protocol_message(field: str, value: object) -> None:
    message = {**VALID_MESSAGE, field: value}
    with pytest.raises(ValidationError):
        validate(message)


def test_unknown_envelope_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        validate({**VALID_MESSAGE, "secret": "must-not-leak"})


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("task.progress", {"percent": 101}),
        ("clarification.requested", {"question": "missing schema"}),
        ("budget_extension.requested", {"requested_tokens": 0, "reason": "no"}),
        ("task.result_submitted", {}),
        ("agent.capacity_updated", {"status": "online"}),
    ],
)
def test_versioned_event_payloads_are_strict(
    event_type: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        validate({**VALID_MESSAGE, "type": event_type, "payload": payload})


VALID_PAYLOADS: dict[str, dict[str, object]] = {
    "agent.register": {"resume_from_sequence": 0},
    "agent.registered": {
        "connection_id": "connection_1",
        "generation": 1,
        "resume_from_sequence": 0,
    },
    "agent.heartbeat": {"acknowledged_sequence": 0},
    "agent.capacity_updated": {
        "status": "draining",
        "max_concurrent_runs": 1,
        "active_runs": 0,
        "queue_capacity": 1,
        "estimated_wait_seconds": 0,
        "supported_offering_versions": [],
    },
    "task.offer": {
        "task_id": "task_1",
        "schema_version_id": "text.summarize@1.0",
        "completion_deadline": "2026-08-12T12:00:00Z",
        "budget_tokens": 100,
        "input": {"text": "hello"},
        "input_artifact_ids": ["artifact_1"],
        "acceptance_rules": {"maximum": 100},
    },
    "task.accept": {},
    "task.reject": {"reason": "capacity changed"},
    "task.started": {},
    "task.progress": {"percent": 50, "message": "working"},
    "clarification.requested": {
        "question": "Which focus?",
        "answer_schema": {"type": "object"},
        "default_answer": {},
        "blocking": True,
        "deadline": "2026-08-12T12:00:00Z",
    },
    "clarification.answered": {
        "clarification_id": "clarification_1",
        "round": 1,
        "answer": {},
        "used_default": False,
    },
    "clarification.timed_out": {
        "clarification_id": "clarification_1",
        "round": 1,
        "answer": {},
        "used_default": True,
    },
    "budget_extension.requested": {"requested_tokens": 10, "reason": "more work"},
    "budget_extension.approved": {"request_id": "budget_1", "requested_tokens": 10},
    "budget_extension.rejected": {"request_id": "budget_1", "requested_tokens": 10},
    "artifact.upload_requested": {
        "original_name": "result.txt",
        "kind": "text",
        "mime_type": "text/plain",
        "size_bytes": 4,
        "sha256": "0" * 64,
    },
    "artifact.upload_completed": {"artifact_id": "artifact_1"},
    "task.result_submitted": {"output": {"summary": "done"}},
    "task.rework_requested": {
        "rework_id": "rework_1",
        "reason": "match the rule",
        "acceptance_rule_refs": ["maximum"],
    },
    "task.cancel_requested": {"before_accept": False},
    "task.cancelled": {},
    "task.failed": {"code": "provider_error", "message": "failed safely"},
    "task.completed": {"automatic": False, "settled_tokens": 90},
    "protocol.error": {"code": "invalid_message"},
}


@pytest.mark.parametrize(("event_type", "payload"), VALID_PAYLOADS.items())
def test_every_protocol_event_has_a_strict_versioned_payload(
    event_type: str, payload: dict[str, object]
) -> None:
    validate({**VALID_MESSAGE, "type": event_type, "payload": payload})
    with pytest.raises(ValidationError):
        validate(
            {
                **VALID_MESSAGE,
                "type": event_type,
                "payload": {**payload, "unexpected_contract_drift": True},
            }
        )
