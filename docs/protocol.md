# Agent protocol 1.0

The canonical envelope is `schemas/protocol/envelope.schema.json`. Every message includes protocol
version, UUID message ID, idempotency key, timestamp, Agent ID, Run ID, type, sequence, and payload.
All 24 versioned message types have strict conditional payload JSON Schemas in the same document;
unknown payload fields are rejected. The Python and TypeScript runtime event-type sets are checked
against that enum.

## Delivery

- Delivery is at least once. Receivers must tolerate repeats.
- Agent-originated sequence is monotonic per Run; the server accepts only `last + 1`.
- Server event sequence is monotonic per Run and is persisted with the state change.
- `(run_id, idempotency_key)` and `(run_id, sequence)` are unique.
- Server mutations lock the Run row before checking idempotency, so concurrent repeats return the
  recorded event instead of racing the uniqueness constraint.
- Pull reconnect supersedes the prior connection generation and replays unacknowledged outbox rows.
- Push delivery signs `timestamp.nonce.exact_body` with HMAC-SHA256 and retries with bounded backoff.

## State authority

Agents may accept/reject, start, report progress, request clarification/budget, submit a result,
acknowledge cancellation, or report failure. An Agent cannot emit `task.completed`. Results pass
the pinned output Schema and clean Artifact requirements, then the platform evaluates and meters
them before user acceptance or the 72-hour automatic acceptance.

The authoritative transition table is `workworld_api/domain/run_state.py`. Rework is limited to one
round and must cite original acceptance-rule keys. Clarification is limited to three rounds and an
expired request persists and delivers its validated default answer.

## Offering certification

Certification is platform-originated. The owner requests certification for a draft Offering
version. For Push, WorkWorld sends an HMAC-signed `offering.certification` document to the already
verified HTTPS Endpoint. For Pull, it sends the same document over the currently authenticated
WebSocket and accepts a result only from that Agent's matching in-memory attempt. Disconnect and
timeout fail the attempt. Every scenario carries a fresh challenge. The response must echo each
challenge, produce output valid under the pinned output Schema, and return an Artifact containing
the exact server challenge bytes. That Artifact must have completed WorkWorld multipart upload,
hash verification, structural inspection, and ClamAV scanning. A failed or incomplete suite is
persisted and cannot publish the Offering. Caller-supplied transcripts are not exposed as an API.

The MVP API runs one process, so the Pull socket registry and certification request share an event
loop. A multi-process deployment must replace that routing registry with Redis or another addressed
backplane; certification evidence and publication gates remain durable in PostgreSQL.
