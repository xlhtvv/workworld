# WorkWorld MVP implementation plan

The acceptance baseline is `WORKWORLD_CODEX_MVP_PLAN.md`. A phase is complete only when its listed tests pass; later work must not weaken earlier contracts.

## Execution status (2026-08-12)

| Phase | Implementation | Acceptance evidence |
| --- | --- | --- |
| 1 | Complete | Contract/state/config/API/Web tests and static checks pass; migrations upgrade/downgrade with zero ORM drift, and Compose repeats the drift check on PostgreSQL |
| 2 | Complete | Unit tests and a clean Compose run pass real multipart MinIO custody, SigV4, ClamAV scanning, metadata extraction, retention, explicit TaskArtifact foreign keys, graded input visibility, and cross-tenant denial |
| 3 | Complete | Live Uvicorn Pull replay/ack and real CA-verified HTTPS Push signature/callback tests pass; clean Compose certifies the real Pull Agent through an 11-check MinIO/ClamAV Artifact challenge before publication |
| 4 | Complete | Recommendation, visibility, sealed applications, selection, and automatic quota tests pass; real PostgreSQL winner/capacity serialization, the full-stack recommended path, and a two-provider sealed open-call journey pass |
| 5 | Complete | All 24 payload contracts, protocol/state/outbox/SSE/control tests pass; server mutations lock before idempotency checks, and clean Compose completes Pull and signed-TLS Push Runs, clarification default, one rework, post-accept cancellation, result upload, evaluation, and settlement |
| 6 | Implemented | Measurement/evaluation/ledger tests and real PostgreSQL concurrent overspend/daily-grant checks pass; OpenAI mode sends integrity-checked image bytes, but no live key is configured |
| 7 | Implemented | Acceptance/rework/reputation tests pass; optional hosted text/image, audio-transcript, and sampled-video moderation is fail-closed; live hosted calls remain unaccepted |
| 8 | Complete | SDKs compile/package; all three provider-hosted examples run; Web production build and 5 Chromium journeys pass; clean Compose covers specified E2E #1–#12, real Redis throttling, including Push, real media Artifacts, clarification, cancellation, and rework/review |

No skipped, mocked, or SQLite-only test is counted as proof for a real PostgreSQL, MinIO, ClamAV,
Redis, Agent transport, or browser acceptance gate.

## Phase 1 — Foundation and contracts

- Monorepo layout for FastAPI API, worker, Next.js Web, Python/TypeScript SDKs, examples, schemas, and infrastructure.
- Domain glossary, architectural decisions, versioned protocol envelope/payload schemas, Run transition table, OpenAPI baseline, bilingual shell, health endpoints, CI and developer commands.
- Tests: protocol JSON Schema validation, transition table completeness/forbidden transitions, configuration parsing, API health, TypeScript checks, Compose validation where Docker is available.

## Phase 2 — Identity, Schema catalog, and Artifact custody

- PostgreSQL migrations for users/sessions/RBAC, immutable Schema versions, Artifact records, access grants, scans, measurements, and retention.
- Twelve Draft 2020-12 standard task schemas and form annotations.
- Multipart MinIO upload confirmation, server-computed SHA-256, MIME/extension checks, real ClamAV scan, safe archive inspection, metadata extraction, scoped short-lived download grants.
- Tests: auth and cross-tenant access, all schema examples, real MinIO/ClamAV integration, archive limits, retention transitions.

## Phase 3 — Agents, endpoints, Offerings

- Hashed/rotatable Agent credentials, Pull tokens and connections, Push challenge and signatures, heartbeat/capacity snapshots, immutable Offering versions, certification workflow and marketplace reads.
- Tests: real WebSocket reconnect/resume, real local HTTPS Push endpoint, nonce replay rejection, SSRF redirect/DNS rebinding defenses, certification failure blocks publication.

## Phase 4 — Tasks, recommendation, and open call

- Schema-driven Task versions and visibility projection; deterministic hard filters and explainable ranking; sealed manual/automatic applications; atomic winner selection and slot reservation.
- Tests: score vectors, privacy projections, sealed candidates, concurrent selection/capacity races, automatic-application quotas.

## Phase 5 — Execution protocol

- Transactional Run state machine, durable event outbox, at-least-once delivery, accept/reject/progress, SSE resume, clarification defaults, budget extension, uploads, cancellation, disconnect grace, deadline timeout.
- Tests: full Pull and Push Runs, duplicate/out-of-order messages, reconnect and SSE replay, timeout/cancellation races, max-three clarifications.

## Phase 6 — Measurement, evaluation, and ledger

- Per-media measurement strategies, hard validators, replaceable OpenAI evaluator plus explicitly marked deterministic local evaluator, immutable formula/rubric versions, balanced signup/daily/hold/settle/partial/refund flows.
- Tests: real media fixtures, validator failures, quality bounds, evaluation audit hashes, ledger reconstruction/idempotency, concurrent overspend and daily claim.

## Phase 7 — Acceptance, reputation, and moderation

- One rework, 72-hour auto-acceptance, partial cancellation settlement, reputation aggregates, verified reviews/replies, automatic text/media moderation.
- Tests: acceptance timers, rework limit/scope, valid-progress partial settlement, review uniqueness/visibility, moderation blocks and audit.

## Phase 8 — Product surface, SDKs, examples, and hardening

- Complete bilingual responsive Web and admin views; installable Python/TypeScript SDKs generated/checked against contracts; Pull text, Push JSON, and Pillow media Agents; operational/security docs.
- Tests: the 12 specified Playwright journeys against real local services, SDK contract suites, lint/type checks, security suite, clean-start Compose smoke test.

## High-risk boundaries and required controls

| Boundary | Failure mode | Control and proof |
| --- | --- | --- |
| Protocol delivery | duplicate or reordered messages mutate twice | unique `(run_id,idempotency_key)`, expected sequence under row lock, replay tests |
| Run state | Agent skips validation or completes directly | centralized transition graph; platform-only transitions; exhaustive tests |
| Winner/capacity | two winners or oversubscribed Agent | Task and capacity row locks; unique active Run/slot constraints; race test |
| Ledger | double spend, duplicate grants, unbalanced settlement | row locks, unique business keys, deferred balance check, reconstruction/race tests |
| Artifact upload | object substitution, malicious archive, cross-tenant URL | confirm object hash/size server-side, quarantine until ClamAV/inspection, scoped grants |
| Push networking | SSRF, DNS rebinding, replay | HTTPS only, resolve every hop, blocked CIDRs, pinned address policy, nonce/timestamp store |
| Pull recovery | split brain after disconnect | connection generation and five-minute lease; acknowledged sequence resume |
| Deadline/cancel/result | competing terminal decisions | locked Run with deterministic precedence and immutable event/outbox transaction |
| Evaluation | model output treated as authority/code | structured validation, hard checks first, no execution privileges, audited mode/version/hash |
| Versioning | historical behavior silently changes | immutable published rows; every Task/Run/evaluation/settlement pins versions |
