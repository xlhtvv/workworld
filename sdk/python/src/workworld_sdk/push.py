import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

MAX_BODY_BYTES = 2 * 1024 * 1024


class PushVerificationError(ValueError):
    pass


class NonceStore:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def use(self, nonce: str, expires_at: float, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > current}
        if nonce in self._seen:
            return False
        self._seen[nonce] = expires_at
        return True


def verify_push_request(
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    nonces: NonceStore,
    *,
    now: float | None = None,
    max_skew_seconds: int = 300,
) -> dict[str, Any]:
    if len(body) > MAX_BODY_BYTES:
        raise PushVerificationError("webhook_body_too_large")
    normalized = {key.lower(): value for key, value in headers.items()}
    timestamp_text = normalized.get("x-workworld-timestamp")
    nonce = normalized.get("x-workworld-nonce")
    signature = normalized.get("x-workworld-signature")
    if timestamp_text is None or nonce is None or signature is None:
        raise PushVerificationError("webhook_headers_missing")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise PushVerificationError("webhook_timestamp_invalid") from exc
    current = time.time() if now is None else now
    if abs(current - timestamp) > max_skew_seconds:
        raise PushVerificationError("webhook_timestamp_out_of_range")
    signed = f"{timestamp}.{nonce}.".encode() + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PushVerificationError("webhook_signature_invalid")
    if not nonces.use(nonce, current + max_skew_seconds, now=current):
        raise PushVerificationError("webhook_nonce_replayed")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PushVerificationError("webhook_body_invalid_json") from exc
    if not isinstance(document, dict):
        raise PushVerificationError("webhook_body_must_be_object")
    return document
