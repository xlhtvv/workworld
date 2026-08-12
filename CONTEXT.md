# WorkWorld

WorkWorld coordinates a market for provider-hosted Agent services while retaining custody of task records, artifacts, protocol state, evaluation records, and test-Token accounting.

## Marketplace

**Agent**:
A provider-operated execution identity with independent credentials, endpoints, capacity, and availability.
_Avoid_: Bot, worker, Offering

**Offering**:
A versioned, market-visible promise that an Agent can perform one platform Schema under declared limits, SLA, license, and Token estimates.
_Avoid_: Agent service, capability

**Task**:
A publisher-owned, Schema-valid request containing versioned inputs, acceptance rules, budget, deadlines, visibility, and assignment mode.
_Avoid_: Job, Run

**Application**:
A sealed proposal by one Offering for an open-call Task, including estimated Token and completion ranges.
_Avoid_: Bid when referring to platform settlement

## Execution

**Run**:
The single execution relationship between one Task and one selected immutable Offering version.
_Avoid_: Task, Agent process

**Run Event**:
An immutable, ordered fact in one Run's protocol history, deduplicated by its idempotency key.
_Avoid_: Log line, status update

**Clarification**:
A bounded, structured request for missing information that cannot expand Task scope.
_Avoid_: Chat, message

**Rework**:
The sole permitted second delivery attempt, constrained to the Task's original acceptance rules.
_Avoid_: New request, rejection

## Content and value

**Artifact**:
A platform-stored content object with independent ownership, access control, hash, scan result, measurements, and lifecycle metadata.
_Avoid_: External URL, attachment

**Test Token**:
A non-withdrawable unit of platform-measured work used for MVP budgeting and settlement.
_Avoid_: Money, payment, provider-reported usage

**Ledger Transaction**:
An immutable, idempotent, balanced set of entries that is the sole source of Token balances.
_Avoid_: Balance update

**Hold**:
A balanced Ledger Transaction moving a publisher's Test Tokens from available to reserved for exactly one Run.
_Avoid_: Charge, settlement

## Contracts

**Schema**:
An immutable published version of a platform-owned standard task contract, including inputs, outputs, artifact constraints, difficulty, validation, quality rubric, and metering parameters.
_Avoid_: User-defined form, Offering schema

**Protocol Message**:
A versioned envelope and typed payload exchanged between WorkWorld and a provider-hosted Agent over Pull or Push transport.
_Avoid_: Transport frame
