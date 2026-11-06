# Deployment profiles

RelayOps is a local alpha. Only the profiles below have been run; nothing has been deployed publicly.

## Native development (verified)

Postgres/pgvector in Docker (`compose.yaml` default service), API, worker, and web as native processes
(`make dev`), Ollama native. This is the profile used for the live journey, live tests, and live evaluation.

## Container app profile (verified locally)

```bash
make images                                   # docker compose --profile app build
docker compose --env-file .env --profile app up -d --wait api web worker
```

Services: `migrate` (Alembic plus checkpointer tables, exits), `api` (`127.0.0.1:8021`), `worker`, `web`
(`127.0.0.1:3021`, Next.js standalone, proxies `/api` to the API container). The backend containers reach the host's
Ollama at `host.docker.internal:11434`. Verified: images build, API health is OK, login through the web container
works, the API reaches Ollama, and the worker starts. Stop with
`docker compose --env-file .env --profile app rm -sf api web worker migrate`.

## Configuration

All settings use the `RELAYOPS_` prefix (see `.env.example` and `backend/src/relayops/core/config.py`). Required in
any shared environment: a random `RELAYOPS_SESSION_SECRET`, a strong database password, `RELAYOPS_COOKIE_SECURE=true`
behind HTTPS, and `RELAYOPS_WEB_ORIGIN`/`RELAYOPS_API_ORIGIN` set to the real origins (they drive the CSRF Origin
check).

## Operational limits

- One worker process handles jobs sequentially, and one inference runs at a time. Leases are 60 seconds with
  heartbeats; more workers are safe (advisory locks per run) but share the single local model.
- The default run deadline is 420 seconds; per-call timeout 90 seconds; context 8,192 tokens.
- Exact vector search without an approximate index; adequate for the synthetic corpus (54 documents across both organizations) and not
  benchmarked at larger sizes.
- No high-availability or multi-region configuration is provided.

## Health, logs, shutdown, backups

- `GET /api/health` is liveness only (the process answers; no dependencies touched).
- `GET /api/ready` is readiness: the database answers, Alembic is at the head revision, the recorded data mode
  matches the configured one, and the MCP endpoint is running. It returns 503 with the failing check otherwise.
- `RELAYOPS_LOG_FORMAT=json` writes one JSON object per line (timestamp, level, logger, message, request ID,
  method, path, status, duration). Request bodies, cookies, authorization headers, and query strings are never
  logged. Each response carries `X-Request-ID` (a well-formed incoming one is kept; otherwise one is generated).
- Shutdown: the API stops on SIGTERM through uvicorn and closes the MCP session manager in its lifespan. The worker
  stops claiming jobs on SIGTERM or SIGINT and finishes the job in hand; an interrupted job's lease expires and
  another worker resumes it from its checkpoint (tested).
- Several workers can share the queue: claims use `FOR UPDATE SKIP LOCKED` and each run has an advisory lock
  (tested with three concurrent workers).
- `make backup` writes a `pg_dump` of the operational database to `data/backups/` (git-ignored).
  `make restore-check` restores the newest dump (or `FILE=...`) into a scratch database, prints the migration,
  data mode, and row counts, and drops the scratch database. It never restores over a working database; to restore
  for real, stop the services and run `pg_restore --clean -d <database> <file>` yourself.

## Not verified

Kubernetes, managed databases, and TLS termination are not part of this release. The GitHub Issues connector
accepts loopback test services, or `https://api.github.com` for allow-listed repositories when an operator enables it
(ADR 0015). The live path has not been exercised against real GitHub.
