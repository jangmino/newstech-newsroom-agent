.PHONY: doctor setup dev-api dev-web lint test test-web typecheck build check docker-build

doctor:
	@./scripts/doctor.sh

setup:
	pnpm install
	cd apps/api && UV_CACHE_DIR=../../.cache/uv uv sync --dev

dev-api:
	cd apps/api && UV_CACHE_DIR=../../.cache/uv uv run uvicorn newsroom_agent.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log

dev-web:
	pnpm --dir apps/web dev

lint:
	cd apps/api && UV_CACHE_DIR=../../.cache/uv uv run ruff check .

test:
	cd apps/api && UV_CACHE_DIR=../../.cache/uv uv run pytest

test-web:
	pnpm --dir apps/web test

typecheck:
	pnpm --dir apps/web typecheck

build:
	pnpm --dir apps/web build
	cd apps/api && UV_CACHE_DIR=../../.cache/uv uv build

check: lint test test-web typecheck build

docker-build:
	docker build -f infra/Dockerfile -t newstech-newsroom-agent:local .
