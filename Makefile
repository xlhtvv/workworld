.PHONY: test lint typecheck build compose-smoke phase1

test:
	PYTHONPATH=sdk/python/src python -m pytest apps/api/tests sdk/python/tests
	apps/web/node_modules/.bin/tsc -p sdk/typescript/tsconfig.json
	pnpm --dir sdk/typescript test
	pnpm --dir apps/web test

lint:
	python -m ruff check scripts apps/api apps/worker sdk/python examples/python-pull-text-agent examples/python-media-echo-agent
	pnpm --dir apps/web lint

typecheck:
	python -m mypy apps/api/src apps/worker/src
	pnpm --dir apps/web typecheck
	apps/web/node_modules/.bin/tsc -p sdk/typescript/tsconfig.json --noEmit
	apps/web/node_modules/.bin/tsc -p examples/typescript-push-json-agent/tsconfig.json --noEmit

build:
	pnpm --dir apps/web build

compose-smoke:
	bash scripts/compose-smoke.sh

phase1: test lint typecheck
