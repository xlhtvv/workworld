# Contributing to WorkWorld

Thank you for helping improve WorkWorld. The product and acceptance baseline is
[`WORKWORLD_CODEX_MVP_PLAN.md`](WORKWORLD_CODEX_MVP_PLAN.md); repository-specific engineering
rules are in [`AGENTS.md`](AGENTS.md).

## Development setup

Use Python 3.12, Node.js 24, pnpm 10, Docker, and Docker Compose v2.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]' -e ./sdk/python
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir examples/typescript-push-json-agent install --frozen-lockfile
```

Copy `.env.example` to `.env` for local configuration. Never commit `.env`, credentials, private
keys, API keys, or user Artifact data.

## Required checks

Run the checks relevant to the code you changed. Before opening a pull request, run the complete
host suite documented in the README. Changes to protocol payloads must keep the JSON Schema,
OpenAPI, both SDKs, examples, and contract tests aligned.

Acceptance claims for PostgreSQL, Redis, MinIO, ClamAV, Pull/Push Agents, and browser behavior must
come from the real Compose/browser suite:

```sh
bash scripts/compose-smoke.sh
```

The deterministic evaluator is useful for local development but must remain visibly marked
`evaluation_mode=mock`. It is not evidence of a hosted model evaluation.

## Pull requests

- Keep each pull request focused and explain the user-visible or contract-level effect.
- Include migrations for database model changes and verify `alembic check` has no drift.
- Add or update tests for state transitions, idempotency, authorization, and concurrency boundaries.
- Update `.env.example` and documentation when configuration or operational behavior changes.
- Do not weaken the platform/provider execution boundary: provider Agent code never runs in
  WorkWorld platform services.
