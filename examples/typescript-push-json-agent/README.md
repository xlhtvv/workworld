# TypeScript Push JSON Agent

Build the TypeScript SDK first (`tsc -p sdk/typescript/tsconfig.json` from the repository root),
install this package, and set `WORKWORLD_AGENT_CREDENTIAL`,
`WORKWORLD_PUSH_SECRET`, `TLS_CERT_FILE`, and `TLS_KEY_FILE`. The endpoint is HTTPS because the
platform deliberately rejects HTTP and private-network Push endpoints. It handles the endpoint
challenge and performs deterministic `set`/`remove` JSON operations.

From the monorepo, run `pnpm install --frozen-lockfile`, `pnpm build`, and `pnpm start` in this
directory. `pnpm test:process` starts the compiled Agent behind real TLS, sends a signed offer, and
verifies its real HTTP authentication and accept/start/result callbacks.
