# RelayOps developer commands. Each target does what its name says; see docs/development.md.
SHELL := /bin/bash
UV := uv --directory backend
DOCKER_PATH := $(if $(shell command -v docker),,/Applications/Docker.app/Contents/Resources/bin:)
export PATH := $(DOCKER_PATH)$(PATH)

.PHONY: setup up down migrate dev seed reset-db doctor test test-offline test-live e2e e2e-offline \
        eval-offline eval-live-smoke eval-full screenshots demo lint build check-repo images

setup:            ## Generate .env secrets, install pinned deps, start Postgres, migrate
	python3 scripts/setup_env.py
	$(UV) sync --frozen
	cd frontend && npm ci --no-audit --no-fund
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install chromium
	$(MAKE) up
	@echo "Next: ollama pull qwen3:4b-instruct && ollama pull embeddinggemma, then make seed && make dev"

up:               ## Start Postgres/pgvector (127.0.0.1:5440) and apply migrations
	docker compose --env-file .env up -d --wait db
	$(MAKE) migrate

down:             ## Stop project containers (keeps the relayops_pgdata volume)
	docker compose --env-file .env down

migrate:
	$(UV) run alembic upgrade head
	$(UV) run python -c "from relayops.agents.checkpoint import ensure_checkpointer_schema as e; e()"

dev:              ## Run API :8020, worker, and web :3020 natively
	bash scripts/dev.sh

seed:             ## Idempotently seed the synthetic world and demo logins (.local/demo-credentials.json)
	$(UV) run python -m relayops.services.seed

reset-db:         ## Drop and recreate the local demo database, then migrate and seed (destroys local demo data)
	docker compose --env-file .env exec -T db psql -qU relayops -d postgres -c "drop database if exists relayops with (force)" -c "create database relayops"
	$(MAKE) migrate seed

doctor:           ## Check prerequisites and service health
	python3 scripts/doctor.py

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy
	cd frontend && npm run lint && npm run typecheck

test: test-offline ## Alias for the offline suite

test-offline:     ## Backend (fixture provider, real Postgres) and frontend checks; no model required
	$(MAKE) lint
	$(UV) run pytest
	cd frontend && npm test

test-live:        ## Real Ollama checks: model presence, embedding dimension, structured output, a tool-driven run
	$(UV) run pytest -m live -o addopts="-q -p no:cacheprovider" tests/live

e2e:              ## Browser journey against the running stack (make dev); uses whatever provider the stack runs
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=0 npx playwright test e2e/journey.spec.ts

eval-offline:     ## Dataset validation, rules baseline, challenge invariants, regression gate
	$(UV) run python ../evals/runners/run.py --profile offline

eval-live-smoke:  ## Six demos + one validation case per category, rules/rag/agent on the local model
	$(UV) run python ../evals/runners/run.py --profile live-smoke

eval-full:        ## Full benchmark (dev+validation, all systems); long-running; test split stays frozen
	$(UV) run python ../evals/runners/run.py --profile full --systems rules,rag,agent

screenshots:      ## Capture docs/images from the running app
	cd frontend && SCREENSHOTS=1 PLAYWRIGHT_BROWSERS_PATH=0 npx playwright test e2e/screenshots.spec.ts

demo:             ## Seed if needed, check health, and print the walkthrough
	$(MAKE) seed >/dev/null
	DOCTOR_SOFT=1 python3 scripts/doctor.py
	python3 scripts/demo.py

build:
	cd frontend && npm run build

check-repo:       ## Secrets, local-only files, and documentation links
	python3 scripts/check_repo.py

images:           ## Build the container images for the app profile
	docker compose --env-file .env --profile app build
