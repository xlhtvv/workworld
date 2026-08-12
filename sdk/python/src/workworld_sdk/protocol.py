import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

PROTOCOL_EVENT_TYPES = frozenset(
    {
        "agent.register", "agent.registered", "agent.heartbeat", "agent.capacity_updated",
        "task.offer", "task.accept", "task.reject", "task.started", "task.progress",
        "clarification.requested", "clarification.answered", "clarification.timed_out",
        "budget_extension.requested", "budget_extension.approved",
        "budget_extension.rejected", "artifact.upload_requested",
        "artifact.upload_completed", "task.result_submitted", "task.rework_requested",
        "task.cancel_requested", "task.cancelled", "task.failed", "task.completed",
        "protocol.error",
    }
)


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Envelope:
    protocol_version: str
    message_id: str
    idempotency_key: str
    timestamp: str
    agent_id: str
    run_id: str
    type: str
    sequence: int
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        agent_id: str,
        run_id: str,
        event_type: str,
        sequence: int,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> "Envelope":
        if sequence < 1:
            raise ProtocolError("sequence_must_be_positive")
        if event_type not in PROTOCOL_EVENT_TYPES:
            raise ProtocolError("event_type_invalid")
        message_id = str(uuid.uuid4())
        return cls(
            protocol_version="1.0",
            message_id=message_id,
            idempotency_key=idempotency_key or f"{run_id}:{event_type}:{sequence}",
            timestamp=datetime.now(UTC).isoformat(),
            agent_id=agent_id,
            run_id=run_id,
            type=event_type,
            sequence=sequence,
            payload=payload,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
