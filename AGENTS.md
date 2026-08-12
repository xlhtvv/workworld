# WorkWorld repository instructions

- Treat `WORKWORLD_CODEX_MVP_PLAN.md` as the product and acceptance baseline.
- Preserve the distinction between platform-hosted coordination and provider-hosted Agents. Never execute provider Agent code in platform services.
- Keep protocol payloads, OpenAPI, SDKs, and examples aligned through contract tests.
- Centralize Run transitions and guard every mutation with a transaction, idempotency key, and expected state/sequence where applicable.
- The immutable ledger is the source of truth for Token balances. Never update a balance as an independent fact.
- Published Schema, Offering, metering formula, rubric, certification, and protocol versions are immutable.
- Do not represent a deterministic evaluator as a real model evaluation. Persist and display `evaluation_mode=mock` when it is used.
- Do not replace MinIO, ClamAV, PostgreSQL, Redis, Pull/Push Agents, or browser E2E with mocks in acceptance tests.
- Use `pytest`, `ruff`, and `mypy` for Python; use `pnpm` scripts for TypeScript. Run the relevant tests at the end of every phase.
- Never commit secrets. Document configuration in `.env.example`.
