# Development

## Prerequisites

- macOS or Linux with Docker (Docker Desktop on macOS)
- [uv](https://docs.astral.sh/uv/) (the backend pins Python 3.12 in `backend/.python-version`; uv installs it
  project-locally even if the system default is newer)
- Node 24 and npm
- [Ollama](https://ollama.com) running natively on `127.0.0.1:11434` with:
  - `qwen3:4b-instruct` (about 2.5 GB) for generation
  - `embeddinggemma` (about 620 MB, 768-dimension embeddings)

Measured on the development machine (Apple M5, 16 GB): a live bug investigation takes roughly 20-40 seconds with
4 turns and 6 tool calls; the single-pass RAG baseline takes 3-8 seconds per case.

## First run

```bash
make setup      # writes .env (0600) with fresh secrets, installs pinned deps, starts Postgres, migrates
ollama pull qwen3:4b-instruct
ollama pull embeddinggemma
make dev        # operational instance (empty): API on :8020, worker, web on :3020
make doctor     # verify everything is reachable
```

The operational database starts empty and records its data mode; the API and worker refuse to start if the
configured mode does not match. For the synthetic world, use the separate demo database:

```bash
make seed-demo  # creates/migrates the demo database and seeds it; refuses an operational database
make demo-dev   # demo instance: API :8030, worker, web :3030, with a demo banner on every page
```

`make seed-demo` prints counts and the credentials path. `.local/demo-credentials.json` (0600, git-ignored) holds
the three demo accounts (`admin@relayops.local`, `support@relayops.local`, `customer@northstar.local`) with generated
passwords. Re-seeding keeps the same passwords. Passwords are stored in the database as Argon2 hashes only.

The demo world is anchored at the hour you first seed (`RELAYOPS_WORLD_ANCHOR=now`), so deployments, incidents, and
error aggregates are recent. To re-anchor, run `make demo-reset` (backs up, then drops and re-seeds the demo database
only).

## Ports

| Service | Default | Override |
| --- | --- | --- |
| Web | 3020 | `RELAYOPS_WEB_PORT` and `RELAYOPS_WEB_ORIGIN` |
| API | 8020 | `RELAYOPS_API_PORT`, `RELAYOPS_API_ORIGIN`, and `RELAYOPS_API_INTERNAL_URL` for the web proxy |
| Postgres | 5440 (127.0.0.1 only) | `RELAYOPS_DB_PORT` and `RELAYOPS_DATABASE_URL` |
| Container profile | 8021 / 3021 | `RELAYOPS_CONTAINER_API_PORT` / `RELAYOPS_CONTAINER_WEB_PORT` |

`scripts/dev.sh` refuses to start when a port is busy; it never stops other processes.

## Commands

| Target | Purpose |
| --- | --- |
| `make up` / `make down` | Start or stop the project's Postgres container (data stays in the `relayops_pgdata` volume) |
| `make migrate` | Alembic migrations plus LangGraph checkpointer tables |
| `make lint` | ruff, ruff format check, mypy, ESLint, TypeScript |
| `make test-offline` | lint plus pytest (real Postgres, labeled fixture provider) and Vitest |
| `make test-live` | Real Ollama checks; fails when Ollama or a model is missing |
| `make e2e` | Playwright journey against the running stack |
| `make eval-offline` | Deterministic evaluation gates |
| `make eval-live-smoke` | Measured live subset (about 6 minutes on the development machine) |
| `make eval-full` | All dev and validation cases for all four systems, both datasets; resumable; the test splits stay frozen |
| `make screenshots` | Capture `docs/images` from the running app |
| `make check-repo` | Secret patterns, tracked local-only files, documentation links |

## Test profiles

- **Offline (default).** `uv --directory backend run pytest` uses a separate `relayops_test` database and the
  `FixtureProvider`, which returns scripted JSON and hash-based vectors labeled `fixture-hash-v1`. These tests verify
  auth, scope, policies, tools, retrieval filters, the runtime, review binding, concurrency, leases, restart,
  cancellation, replay, actions, artifacts, and exports. They do not measure model quality.
- **Live.** `make test-live` runs `backend/tests/live` against Ollama and asserts `model_provider=ollama`.
- **Browser.** `make e2e` drives whatever stack is running. Locally that is the real model; in CI the stack runs with
  `RELAYOPS_LLM_PROVIDER=fixture RELAYOPS_FIXTURE_SCRIPT=generic`, and runs show a "fixture provider" badge.

Playwright's Chromium is installed into `frontend/node_modules` (`PLAYWRIGHT_BROWSERS_PATH=0`).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Settings shows "Ollama unavailable" or runs fail with `model_unavailable` | Start Ollama, `ollama pull` the models, then press "Retry from checkpoint" on the run |
| "embedding dimension ... does not match" | The configured embedding model is not 768-d; use `embeddinggemma` or change `RELAYOPS_EMBED_DIM` and re-seed into a fresh database |
| Settings shows "model mismatch" for the index | The index was built with another embedding model; re-ingest the documents (demo: `make demo-reset`) |
| 403 "CSRF token missing or invalid" from scripts | Send `X-CSRF-Token` equal to the `relayops_csrf` cookie and a matching `Origin` |
| Login returns 429 | Too many failed attempts; wait 15 minutes |
| Run stays `queued` | The worker is not running; `make dev` starts it |
