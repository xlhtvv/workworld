#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "compose smoke requires Docker with Compose v2; docker was not found" >&2
  exit 127
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "compose smoke requires Docker Compose v2" >&2
  exit 127
fi

if [[ -n "${PYTHON:-}" ]]; then
  python_bin="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  python_bin=.venv/bin/python
else
  python_bin=python3
fi
push_cert_dir="$(mktemp -d /tmp/workworld-push-certs.XXXXXX)"
push_runtime_dir="$(mktemp -d /tmp/workworld-push-runtime.XXXXXX)"
export WORKWORLD_PUSH_CERT_DIR="$push_cert_dir"
export WORKWORLD_PUSH_RUNTIME_DIR="$push_runtime_dir"
export PUSH_ALLOWED_PRIVATE_HOSTS='["minio"]'
export PUSH_CA_FILE=/push-certs/ca.crt
compose=(docker compose --profile acceptance -p workworld-smoke)
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
  rm -rf -- "$push_cert_dir" "$push_runtime_dir"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj /CN=WorkWorld-Local-Push-CA \
  -keyout "$push_cert_dir/ca.key" -out "$push_cert_dir/ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -subj /CN=minio \
  -addext subjectAltName=DNS:minio \
  -keyout "$push_cert_dir/server.key" -out "$push_cert_dir/server.csr" >/dev/null 2>&1
printf 'subjectAltName=DNS:minio\n' > "$push_cert_dir/server.ext"
openssl x509 -req -days 1 -in "$push_cert_dir/server.csr" \
  -CA "$push_cert_dir/ca.crt" -CAkey "$push_cert_dir/ca.key" -CAcreateserial \
  -extfile "$push_cert_dir/server.ext" -out "$push_cert_dir/server.crt" >/dev/null 2>&1
touch "$push_runtime_dir/credential"
chmod 600 "$push_runtime_dir/credential"
apps/web/node_modules/.bin/tsc -p sdk/typescript/tsconfig.json
apps/web/node_modules/.bin/tsc -p examples/typescript-push-json-agent/tsconfig.json
"${compose[@]}" down --volumes --remove-orphans
"${compose[@]}" up --build --detach --wait --wait-timeout 420
curl --fail --retry 40 --retry-all-errors --retry-delay 5 http://localhost:8000/health/ready
curl --fail --retry 20 --retry-all-errors --retry-delay 3 http://localhost:3000/en
"${compose[@]}" exec -T api alembic check
"${python_bin}" scripts/real_artifact_smoke.py
"${compose[@]}" exec -T api python /app/scripts/real_postgres_races.py
"${python_bin}" scripts/real_pull_journey.py
"${python_bin}" scripts/real_open_call_journey.py
"${python_bin}" scripts/real_control_journeys.py
"${python_bin}" scripts/real_push_journey.py
"${python_bin}" scripts/real_media_journey.py
pnpm --dir apps/web test:e2e:compose
"${compose[@]}" exec -T api python /app/scripts/real_security_journey.py
