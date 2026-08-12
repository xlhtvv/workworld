import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.domain.run_state import RunState
from workworld_api.finance_models import LedgerTransaction
from workworld_api.market_models import Agent, AgentConnection, AgentEndpoint
from workworld_api.models import Artifact, ScanStatus, User
from workworld_api.services.acceptance import AcceptanceError, AcceptanceService
from workworld_api.services.evaluation import (
    EvaluationError,
    EvaluationService,
    OpenAIResponsesEvaluator,
    seed_evaluation_versions,
)
from workworld_api.services.ledger import LedgerService
from workworld_api.services.protocol import ProtocolError, ProtocolService
from workworld_api.services.run_control import RunControlError, RunControlService
from workworld_api.task_models import (
    BudgetExtensionRequest,
    ClarificationRequest,
    ProtocolOutbox,
    Run,
    RunEvent,
    RunSlotReservation,
    Task,
    TaskInputVersion,
)


def envelope(
    sequence: int,
    event_type: str,
    payload: dict[str, object] | None = None,
    *,
    key: str | None = None,
) -> dict[str, object]:
    return {
        "protocol_version": "1.0",
        "message_id": f"00000000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": key or f"agent-event-{sequence}",
        "timestamp": datetime.now(UTC).isoformat(),
        "agent_id": "agent_1",
        "run_id": "run_1",
        "type": event_type,
        "sequence": sequence,
        "payload": payload or {},
    }


def add_run(db: Session) -> Run:
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
        schema_id="text.summarize",
        schema_version="1.0",
        title="Task",
        public_summary="Task",
        input_json={"text": "input", "difficulty": "simple"},
        field_visibility={},
        difficulty="simple",
        acceptance_rules={"max_characters": 1000},
        budget_tokens=100,
        completion_deadline=now + timedelta(hours=1),
        assignment_mode="recommended",
        status="candidate_selected",
        created_at=now,
    )
    run = Run(
        id="run_1",
        task_id="task_1",
        attempt=1,
        offering_version_id="offering_version_1",
        agent_id="agent_1",
        state=RunState.OFFER_SENT,
        protocol_version="1.0",
        schema_version_id="text.summarize@1.0",
        last_agent_sequence=0,
        next_event_sequence=1,
        clarification_rounds=0,
        rework_count=0,
        offer_expires_at=now + timedelta(minutes=10),
        completion_deadline=now + timedelta(hours=1),
        created_at=now,
    )
    db.add_all(
        [
            publisher,
            provider,
            agent,
            task,
            run,
            RunSlotReservation(
                id="slot_1",
                run_id=run.id,
                agent_id=run.agent_id,
                status="active",
                reserved_at=now,
            ),
        ]
    )
    db.commit()
    return run


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add_run(session)
        yield session


def test_agent_events_are_ordered_idempotent_and_authorized(db: Session) -> None:
    service = ProtocolService(db)
    accepted = service.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    duplicate = service.ingest_agent_message(
        "agent_1", envelope(1, "task.accept", key="agent-event-1")
    )
    assert duplicate.id == accepted.id
    assert db.query(RunEvent).count() == 1

    with pytest.raises(ProtocolError, match="run_not_found"):
        service.ingest_agent_message(
            "agent_other", envelope(1, "task.accept", key="agent-event-1")
        )
    with pytest.raises(ProtocolError, match="agent_sequence_out_of_order"):
        service.ingest_agent_message("agent_1", envelope(3, "task.started"))
    with pytest.raises(ProtocolError, match="agent_cannot_complete_run"):
        service.ingest_agent_message("agent_1", envelope(2, "task.completed"))

    run = db.get(Run, "run_1")
    assert run is not None
    assert run.state == RunState.ACCEPTED
    assert run.last_agent_sequence == 1
    assert run.next_event_sequence == 2


def test_reject_reopens_attempt_and_releases_capacity(db: Session) -> None:
    event = ProtocolService(db).ingest_agent_message("agent_1", envelope(1, "task.reject"))
    run = db.get(Run, "run_1")
    slot = db.get(RunSlotReservation, "slot_1")
    assert event.sequence == 1
    assert run is not None and run.state == RunState.OPEN
    assert slot is not None and slot.status == "released"


def test_clarification_payload_and_three_round_limit(db: Session) -> None:
    service = ProtocolService(db)
    service.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    service.ingest_agent_message("agent_1", envelope(2, "task.started"))

    with pytest.raises(ProtocolError, match="clarification.requested_payload_invalid"):
        service.ingest_agent_message("agent_1", envelope(3, "clarification.requested"))
    run = db.get(Run, "run_1")
    assert run is not None and run.state == RunState.RUNNING
    assert run.last_agent_sequence == 2

    for round_number in range(1, 4):
        sequence = round_number + 2
        service.ingest_agent_message(
            "agent_1",
            envelope(
                sequence,
                "clarification.requested",
                {
                    "question": f"Question {round_number}",
                    "answer_schema": {"type": "object"},
                    "default_answer": {},
                    "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
            ),
        )
        service.server_event(
            "run_1",
            event_type="clarification.answered",
            target_state=RunState.RUNNING,
            actor_type="publisher",
            actor_id="user_1",
            payload={"round": round_number, "answer": {}},
            idempotency_key=f"answer-{round_number}",
            deliver_to_agent=True,
        )

    with pytest.raises(ProtocolError, match="clarification_round_limit"):
        service.ingest_agent_message(
            "agent_1",
            envelope(
                6,
                "clarification.requested",
                {
                    "question": "One too many",
                    "answer_schema": {"type": "object"},
                    "default_answer": {},
                    "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
            ),
        )
    assert db.scalar(select(Run).where(Run.id == "run_1")).clarification_rounds == 3
    assert db.query(ClarificationRequest).count() == 3
    assert db.query(ProtocolOutbox).count() == 3


def test_server_terminal_event_releases_slot_and_is_idempotent(db: Session) -> None:
    service = ProtocolService(db)
    service.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    event = service.server_event(
        "run_1",
        event_type="task.cancel_requested",
        target_state=RunState.CANCELLATION_REQUESTED,
        actor_type="publisher",
        actor_id="user_1",
        payload={},
        idempotency_key="cancel-request-1",
        deliver_to_agent=True,
    )
    duplicate = service.server_event(
        "run_1",
        event_type="task.cancel_requested",
        target_state=RunState.CANCELLATION_REQUESTED,
        actor_type="publisher",
        actor_id="user_1",
        payload={},
        idempotency_key="cancel-request-1",
        deliver_to_agent=True,
    )
    assert duplicate.id == event.id
    assert db.query(ProtocolOutbox).count() == 1

    service.ingest_agent_message("agent_1", envelope(2, "task.cancelled"))
    slot = db.get(RunSlotReservation, "slot_1")
    assert slot is not None and slot.status == "released"


def test_outbox_retries_until_scoped_acknowledgement(db: Session) -> None:
    service = ProtocolService(db)
    service.server_event(
        "run_1",
        event_type="task.offer",
        target_state=None,
        actor_type="system",
        actor_id=None,
        payload={},
        idempotency_key="offer-1",
        deliver_to_agent=True,
    )
    first = service.pending_outbox("agent_1", force=True)
    second = service.pending_outbox("agent_1", force=True)
    assert [event.id for _, event in first] == [event.id for _, event in second]
    event_id = first[0][1].id
    assert service.acknowledge_outbox("agent_other", [event_id]) == 0
    assert service.acknowledge_outbox("agent_1", [event_id]) == 1
    assert service.pending_outbox("agent_1", force=True) == []


def test_outbox_accepts_wire_message_id_acknowledgement(db: Session) -> None:
    service = ProtocolService(db)
    event = service.server_event(
        "run_1",
        event_type="task.offer",
        target_state=None,
        actor_type="system",
        actor_id=None,
        payload={},
        idempotency_key="offer-message-ack",
        deliver_to_agent=True,
    )
    assert service.acknowledge_outbox("agent_1", [event.message_id]) == 1
    assert service.pending_outbox("agent_1", force=True) == []


def test_clarification_answer_is_validated_versioned_and_resumed(db: Session) -> None:
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    protocol.ingest_agent_message(
        "agent_1",
        envelope(
            3,
            "clarification.requested",
            {
                "question": "Choose focus",
                "answer_schema": {
                    "type": "object",
                    "required": ["focus"],
                    "properties": {"focus": {"type": "string"}},
                    "additionalProperties": False,
                },
                "default_answer": {"focus": "general"},
                "deadline": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
        ),
    )
    clarification = db.query(ClarificationRequest).one()
    publisher = db.get(User, "user_publisher")
    assert publisher is not None
    control = RunControlService(db)
    with pytest.raises(RunControlError, match="clarification_answer_invalid"):
        control.answer_clarification(publisher, "run_1", clarification.id, {"wrong": True})
    with pytest.raises(RunControlError, match="content_blocked:contact_email"):
        control.answer_clarification(
            publisher, "run_1", clarification.id, {"focus": "outside@example.com"}
        )
    event = control.answer_clarification(
        publisher, "run_1", clarification.id, {"focus": "security"}
    )
    run = db.get(Run, "run_1")
    version = db.query(TaskInputVersion).filter_by(task_id="task_1", version=1).one()
    assert event.event_type == "clarification.answered"
    assert run is not None and run.state == RunState.RUNNING
    assert version.input_json["clarification"]["answer"] == {"focus": "security"}


def test_budget_request_requires_publisher_and_updates_state(db: Session) -> None:
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    with pytest.raises(ProtocolError, match="content_blocked:external_payment"):
        protocol.ingest_agent_message(
            "agent_1",
            envelope(
                3,
                "budget_extension.requested",
                {"requested_tokens": 25, "reason": "Pay the extra by PayPal"},
            ),
        )
    protocol.ingest_agent_message(
        "agent_1",
        envelope(
            3,
            "budget_extension.requested",
            {"requested_tokens": 25, "reason": "More source material"},
        ),
    )
    request = db.query(BudgetExtensionRequest).one()
    publisher = db.get(User, "user_publisher")
    provider = db.get(User, "user_provider")
    assert publisher is not None and provider is not None
    with pytest.raises(RunControlError, match="publisher_required"):
        RunControlService(db).decide_budget(provider, "run_1", request.id, approve=True)
    event = RunControlService(db).decide_budget(
        publisher, "run_1", request.id, approve=False
    )
    run = db.get(Run, "run_1")
    assert event.event_type == "budget_extension.rejected"
    assert run is not None and run.state == RunState.RUNNING


def test_result_is_hard_validated_before_state_changes(db: Session) -> None:
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    with pytest.raises(ProtocolError, match="result_output_schema_invalid"):
        protocol.ingest_agent_message(
            "agent_1", envelope(3, "task.result_submitted", {"output": {"wrong": "x"}})
        )
    run = db.get(Run, "run_1")
    assert run is not None and run.state == RunState.RUNNING
    assert run.last_agent_sequence == 2

    with pytest.raises(ProtocolError, match="content_blocked:contact_email"):
        protocol.ingest_agent_message(
            "agent_1",
            envelope(
                3,
                "task.result_submitted",
                {"output": {"summary": "Contact outside@example.com"}},
            ),
        )
    assert run.state == RunState.RUNNING
    assert run.last_agent_sequence == 2

    event = protocol.ingest_agent_message(
        "agent_1",
        envelope(3, "task.result_submitted", {"output": {"summary": "Safe result"}}),
    )
    assert event.event_type == "task.result_submitted"
    assert run.state == RunState.RESULT_SUBMITTED


def test_offer_timeout_is_terminal_and_releases_slot(db: Session) -> None:
    run = db.get(Run, "run_1")
    assert run is not None
    run.offer_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert RunControlService(db).sweep_deadlines() == 1
    assert run.state == RunState.TIMED_OUT
    slot = db.get(RunSlotReservation, "slot_1")
    assert slot is not None and slot.status == "released"
    assert RunControlService(db).sweep_deadlines() == 0


def test_expired_clarification_uses_validated_default(db: Session) -> None:
    db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    protocol.ingest_agent_message(
        "agent_1",
        envelope(
            3,
            "clarification.requested",
            {
                "question": "Choose focus",
                "answer_schema": {
                    "type": "object",
                    "required": ["focus"],
                    "properties": {"focus": {"type": "string"}},
                },
                "default_answer": {"focus": "general"},
                "deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
        ),
    )
    assert RunControlService(db).default_expired_clarifications() == 1
    request = db.query(ClarificationRequest).one()
    run = db.get(Run, "run_1")
    assert request.status == "defaulted"
    assert request.answer_json == {"focus": "general"}
    assert run is not None and run.state == RunState.RUNNING


def test_pull_disconnect_grace_and_recovery_preserve_run_state(db: Session) -> None:
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    old = datetime.now(UTC) - timedelta(minutes=6)
    db.add_all(
        [
            AgentEndpoint(
                id="endpoint_pull",
                agent_id="agent_1",
                endpoint_type="pull",
                status="verified",
                resolved_addresses=[],
                verified_at=old,
                created_at=old,
            ),
            AgentConnection(
                id="connection_old",
                agent_id="agent_1",
                generation=1,
                connected_at=old,
                heartbeat_at=old,
                disconnected_at=old,
                acknowledged_sequence=0,
            ),
        ]
    )
    db.commit()
    control = RunControlService(db)
    assert control.mark_unreachable_agents() == 1
    run = db.get(Run, "run_1")
    assert run is not None and run.state == RunState.AGENT_UNREACHABLE
    assert control.recover_agent("agent_1") == 1
    assert run.state == RunState.RUNNING


def test_result_is_evaluated_and_metered_with_explicit_mock_mode(db: Session) -> None:
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    protocol.ingest_agent_message("agent_1", envelope(2, "task.started"))
    protocol.ingest_agent_message(
        "agent_1",
        envelope(3, "task.result_submitted", {"output": {"summary": "Safe result"}}),
    )
    seed_evaluation_versions(db)
    evaluation = EvaluationService(db, Settings(evaluation_mode="mock")).evaluate_run("run_1")
    run = db.get(Run, "run_1")
    assert evaluation.evaluation_mode == "mock"
    assert evaluation.model == "deterministic_stub_v1"
    assert run is not None and run.state == RunState.WAITING_FOR_ACCEPTANCE
    assert run.quality_score == 80
    assert run.measured_tokens is not None and 0 < run.measured_tokens <= 100
    assert run.acceptance_deadline is not None


def test_openai_evaluator_builds_real_multimodal_responses_input() -> None:
    evaluator = OpenAIResponsesEvaluator("test-key", "gpt-5-mini")
    document = evaluator.request_document(
        {
            "task_input": {"prompt": "edit"},
            "task_output": {"description": "done"},
            "image_inputs": [
                {
                    "artifact_id": "artifact_1",
                    "direction": "output",
                    "data_url": "data:image/png;base64,iVBORw0KGgo=",
                }
            ],
        },
        ["preserve the requested subject"],
    )
    content = document["input"][1]["content"]
    assert content[0]["type"] == "input_text"
    assert "data:image" not in content[0]["text"]
    assert content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,iVBORw0KGgo=",
        "detail": "auto",
    }


def test_openai_evaluator_rejects_malformed_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            output = json.dumps({"quality_score": True, "evidence": [], "issues": []})
            return json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": output}],
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    evaluator = OpenAIResponsesEvaluator("test-key", "gpt-5-mini")
    with pytest.raises(EvaluationError, match="openai_evaluation_score_invalid"):
        evaluator.evaluate({"task_input": {}, "task_output": {}}, ["quality"])


def test_rework_is_limited_to_original_rules_and_only_once(db: Session) -> None:
    run = db.get(Run, "run_1")
    publisher = db.get(User, "user_publisher")
    assert run is not None and publisher is not None
    run.state = RunState.WAITING_FOR_ACCEPTANCE
    run.measured_tokens = 50
    db.commit()
    service = AcceptanceService(db)
    with pytest.raises(AcceptanceError, match="rework_scope_expansion_forbidden"):
        service.request_rework(publisher, run.id, "New demand", ["new_requirement"])
    request = service.request_rework(
        publisher, run.id, "Summary is too long", ["max_characters"]
    )
    assert request.acceptance_rule_refs == ["max_characters"]
    assert run.state == RunState.REWORK_REQUESTED
    ProtocolService(db).ingest_agent_message("agent_1", envelope(1, "task.started"))
    assert run.state == RunState.REWORKING
    run.state = RunState.WAITING_FOR_ACCEPTANCE
    db.commit()
    with pytest.raises(AcceptanceError, match="rework_not_available"):
        service.request_rework(publisher, run.id, "Again", ["max_characters"])


def test_automatic_acceptance_settles_held_budget_without_rejection(db: Session) -> None:
    run = db.get(Run, "run_1")
    publisher = db.get(User, "user_publisher")
    assert run is not None and publisher is not None
    ledger = LedgerService(db)
    ledger.signup_grant(publisher)
    ledger.hold(publisher.id, "task_1", 100)
    db.commit()
    run.state = RunState.WAITING_FOR_ACCEPTANCE
    run.measured_tokens = 75
    run.acceptance_deadline = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert AcceptanceService(db).auto_accept_due() == 1
    assert run.state == RunState.COMPLETED
    assert ledger.balances(publisher.id)["user_available"] == 99_925
    assert ledger.balances("user_provider")["provider_available"] == 75


def test_cancel_without_verified_pre_cancel_output_refunds_the_full_hold(db: Session) -> None:
    run = db.get(Run, "run_1")
    publisher = db.get(User, "user_publisher")
    assert run is not None and publisher is not None
    ledger = LedgerService(db)
    ledger.signup_grant(publisher)
    ledger.hold(publisher.id, "task_1", 100)
    db.commit()
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    RunControlService(db).cancel(publisher, run.id)
    db.add(
        Artifact(
            id="artifact_after_cancel",
            owner_id="user_provider",
            task_id="task_1",
            direction="output",
            kind="text",
            mime_type="text/plain",
            declared_mime_type="text/plain",
            original_name="late.txt",
            size_bytes=12,
            expected_size_bytes=12,
            sha256="a" * 64,
            expected_sha256="a" * 64,
            storage_key="artifacts/late",
            multipart_upload_id=None,
            scan_status=ScanStatus.CLEAN,
            metadata_json={"token_count": 12},
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    db.commit()
    protocol.ingest_agent_message("agent_1", envelope(2, "task.cancelled"))

    assert AcceptanceService(db).settle_terminal_runs() == 1
    transaction = db.scalar(
        select(LedgerTransaction).where(LedgerTransaction.reference_id == "task_1")
        .order_by(LedgerTransaction.created_at.desc())
    )
    assert transaction is not None and transaction.transaction_type == "task_refund"
    assert ledger.balances(publisher.id)["user_available"] == 100_000
    assert ledger.balances("user_provider")["provider_available"] == 0


def test_cancel_partially_settles_only_verified_output_uploaded_before_request(
    db: Session,
) -> None:
    run = db.get(Run, "run_1")
    publisher = db.get(User, "user_publisher")
    assert run is not None and publisher is not None
    ledger = LedgerService(db)
    ledger.signup_grant(publisher)
    ledger.hold(publisher.id, "task_1", 100)
    db.add(
        Artifact(
            id="artifact_before_cancel",
            owner_id="user_provider",
            task_id="task_1",
            direction="output",
            kind="text",
            mime_type="text/plain",
            declared_mime_type="text/plain",
            original_name="stage.txt",
            size_bytes=20,
            expected_size_bytes=20,
            sha256="b" * 64,
            expected_sha256="b" * 64,
            storage_key="artifacts/stage",
            multipart_upload_id=None,
            scan_status=ScanStatus.CLEAN,
            metadata_json={"token_count": 20},
            created_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db.commit()
    protocol = ProtocolService(db)
    protocol.ingest_agent_message("agent_1", envelope(1, "task.accept"))
    RunControlService(db).cancel(publisher, run.id)
    protocol.ingest_agent_message("agent_1", envelope(2, "task.cancelled"))

    assert AcceptanceService(db).settle_terminal_runs() == 1
    transaction = db.scalar(
        select(LedgerTransaction).where(LedgerTransaction.reference_id == "task_1")
        .order_by(LedgerTransaction.created_at.desc())
    )
    assert transaction is not None and transaction.transaction_type == "task_partial_settlement"
    assert ledger.balances("user_provider")["provider_available"] == 11
    assert ledger.balances(publisher.id)["user_available"] == 99_989
