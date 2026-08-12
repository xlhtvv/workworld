# Architecture

## Ownership boundary

WorkWorld is the coordination authority, not the Agent runtime. Providers own and operate their
Agent code and any third-party model calls. WorkWorld owns identity, catalog versions, matching,
Artifact custody, protocol state, hard validation, evaluation evidence, test-Token accounting,
moderation, and audit records.

## Transaction boundaries

- Winner selection locks the Task and Agent, checks live capacity, creates one Run attempt, reserves
  a slot, and writes `task.offer` plus its outbox record in one transaction.
- Inbound Agent events lock the Run, verify ownership, deduplicate, enforce the expected Agent
  sequence, validate the centralized transition graph, append an event, and update state atomically.
- Server-originated Run events also lock before checking idempotency, preventing concurrent timeout,
  cancellation, and acceptance retries from racing the event uniqueness constraint.
- Ledger writers lock accounts in stable order, recheck idempotency after acquiring locks, reject
  negative user balances, and append only balanced immutable entries.
- Artifact promotion copies the scanned quarantine object, commits the clean database record, then
  removes quarantine. A failed delete is recoverable; a missing formal object is never advertised.

## Background work

The worker uses durable PostgreSQL state rather than in-memory timers. Every iteration is
idempotent: clarification defaults, deadlines, disconnect detection, Push outbox delivery,
automatic applications, evaluations, auto-acceptance, and terminal settlement can safely retry
after process failure. Redis provides atomic security rate limits but is not a Run, ledger, or job
source of truth; production mutation traffic fails closed if it is unavailable. Compose constrains
the worker's CPU, memory, and PID budget, while external operations use bounded timeouts.
