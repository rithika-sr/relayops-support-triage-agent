# RelayOps developer commands. Each target does what its name says; see docs/development.md.
SHELL := /bin/bash
UV := uv --directory backend
DOCKER_PATH := $(if $(shell command -v docker),,/Applications/Docker.app/Contents/Resources/bin:)
export PATH := $(DOCKER_PATH)$(PATH)
-include .env
# The demo instance selects RELAYOPS_DEMO_DATABASE_URL inside the app config; no URL appears on command lines.
DEMO_ENV := RELAYOPS_DATA_MODE=demo \
	RELAYOPS_API_PORT=8030 RELAYOPS_WEB_PORT=3030 RELAYOPS_WEB_ORIGIN=http://localhost:3030 \
	RELAYOPS_API_ORIGIN=http://localhost:8030

.PHONY: restore-check setup up down migrate dev demo-migrate seed-demo demo-dev demo-reset doctor test test-offline test-live e2e e2e-offline \
        eval-offline eval-live-smoke eval-full screenshots demo lint build check-repo images

setup:            ## Generate .env secrets, install pinned deps, start Postgres, migrate
	python3 scripts/setup_env.py
	$(UV) sync --frozen
	cd frontend && npm ci --no-audit --no-fund
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install chromium
	$(MAKE) up
	@echo "Next: ollama pull qwen3:4b-instruct && ollama pull embeddinggemma, then make dev (empty operational instance)"
	@echo "Optional labeled demo: make seed-demo && make demo-dev"

up:               ## Start Postgres/pgvector (127.0.0.1:5440) and apply migrations
	docker compose --env-file .env up -d --wait db
	$(MAKE) migrate

down:             ## Stop project containers (keeps the relayops_pgdata volume)
	docker compose --env-file .env down

migrate:          ## Create (if missing) and migrate the operational database; records its data mode
	@python3 scripts/ensure_db.py RELAYOPS_DATABASE_URL
	$(UV) run alembic upgrade head
	$(UV) run python -c "from relayops.agents.checkpoint import ensure_checkpointer_schema as e; e()"
	$(UV) run python -m relayops.core.instance

dev:              ## Run API :8020, worker, and web :3020 natively
	bash scripts/dev.sh

demo-migrate:     ## Create and migrate the separate demo database (data mode: demo)
	@python3 scripts/ensure_db.py RELAYOPS_DEMO_DATABASE_URL
	$(DEMO_ENV) $(UV) run alembic upgrade head
	$(DEMO_ENV) $(UV) run python -c "from relayops.agents.checkpoint import ensure_checkpointer_schema as e; e()"
	$(DEMO_ENV) $(UV) run python -m relayops.core.instance

seed-demo: demo-migrate ## Seed the labeled synthetic world into the demo database only (refuses operational)
	$(DEMO_ENV) $(UV) run python -m relayops.services.seed

demo-dev:         ## Run the labeled demo instance on :8030/:3030 against the demo database
	$(DEMO_ENV) bash scripts/dev.sh

demo-reset:       ## Back up, drop, and re-seed the demo database only
	@python3 scripts/backup_db.py RELAYOPS_DEMO_DATABASE_URL
	@docker compose --env-file .env exec -T db psql -qU relayops -d postgres -c "drop database if exists $$(python3 -c "import sys;sys.path.insert(0,'scripts');from ensure_db import _url_from_env as u;print(u('RELAYOPS_DEMO_DATABASE_URL').rsplit('/',1)[1])") with (force)"
	$(MAKE) seed-demo

backup:           ## pg_dump the operational database into data/backups (git-ignored)
	@python3 scripts/backup_db.py RELAYOPS_DATABASE_URL

restore-check:    ## Restore the newest backup into a scratch database, report counts, drop it (FILE= to choose)
	@python3 scripts/restore_check.py $(FILE)

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

demo:             ## Print the demo walkthrough (run make seed-demo and make demo-dev first)
	python3 scripts/demo.py

build:
	cd frontend && npm run build

check-repo:       ## Secrets, local-only files, and documentation links
	python3 scripts/check_repo.py

images:           ## Build the container images for the app profile
	docker compose --env-file .env --profile app build
