# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or include secrets, credentials,
private Artifact data, or exploit details in a public pull request. Use the repository's private
GitHub Security Advisory reporting flow instead. If private reporting is not enabled yet, the
repository owner should enable it under **Settings → Security → Private vulnerability reporting**
before making the repository public.

Include the affected component, reproduction conditions, expected impact, and a minimal safe proof
of concept. Remove API keys, access tokens, cookies, private keys, and user data from all evidence.

## Supported version

WorkWorld is currently an MVP. Security fixes are applied to the latest `main` branch; no older
release line is supported yet.

## Security-sensitive invariants

- Provider Agent code is never uploaded to or executed by platform services.
- The immutable balanced ledger is the source of Token balances.
- Formal Artifacts stay quarantined until structural inspection and a real ClamAV scan succeed.
- Run mutations require centralized transitions, idempotency, expected ordering, and database
  transaction boundaries.
- Published Schema, Offering, formula, rubric, certification, and protocol versions are immutable.
- Hosted evaluation and moderation fail closed and never silently fall back to a mock.

Operational hardening and current limitations are documented in
[`docs/security.md`](docs/security.md).
