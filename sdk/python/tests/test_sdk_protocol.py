import hashlib
import hmac
import json

import pytest
from workworld_sdk.protocol import PROTOCOL_EVENT_TYPES, Envelope, ProtocolError
from workworld_sdk.push import (
    MAX_BODY_BYTES,
    NonceStore,
    PushVerificationError,
    verify_push_request,
)


def test_envelope_has_stable_idempotency_key_and_no_secret_fields() -> None:
    envelope = Envelope.create("agent_1", "run_1", "task.progress", 3, {"percent": 50})
    assert envelope.idempotency_key == "run_1:task.progress:3"
    assert set(envelope.as_dict()) == {
        "protocol_version",
        "message_id",
        "idempotency_key",
        "timestamp",
        "agent_id",
        "run_id",
        "type",
        "sequence",
        "payload",
    }
    assert len(PROTOCOL_EVENT_TYPES) == 24
    with pytest.raises(ProtocolError, match="event_type_invalid"):
        Envelope.create("agent_1", "run_1", "task.unknown", 4, {})


def signed_headers(secret: str, timestamp: int, nonce: str, body: bytes) -> dict[str, str]:
    signature = hmac.new(
        secret.encode(), f"{timestamp}.{nonce}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-WorkWorld-Timestamp": str(timestamp),
        "X-WorkWorld-Nonce": nonce,
        "X-WorkWorld-Signature": signature,
    }


def test_push_signature_accepts_once_and_rejects_replay_or_tampering() -> None:
    secret = "test-push-secret"
    now = 2_000_000_000
    body = json.dumps({"type": "task.offer", "run_id": "run_1"}).encode()
    headers = signed_headers(secret, now, "nonce-1", body)
    nonces = NonceStore()
    assert verify_push_request(headers, body, secret, nonces, now=now)["run_id"] == "run_1"
    with pytest.raises(PushVerificationError, match="webhook_nonce_replayed"):
        verify_push_request(headers, body, secret, nonces, now=now)
    with pytest.raises(PushVerificationError, match="webhook_signature_invalid"):
        verify_push_request(headers, body + b" ", secret, NonceStore(), now=now)


def test_push_signature_rejects_stale_and_oversized_requests() -> None:
    secret = "test-push-secret"
    timestamp = 2_000_000_000
    body = b"{}"
    headers = signed_headers(secret, timestamp, "nonce-2", body)
    with pytest.raises(PushVerificationError, match="webhook_timestamp_out_of_range"):
        verify_push_request(headers, body, secret, NonceStore(), now=timestamp + 301)
    with pytest.raises(PushVerificationError, match="webhook_body_too_large"):
        verify_push_request(
            headers, b"x" * (MAX_BODY_BYTES + 1), secret, NonceStore(), now=timestamp
        )
