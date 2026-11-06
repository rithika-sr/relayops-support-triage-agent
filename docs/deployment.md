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
- No backup, high-availability, or multi-region configuration is provided.

## Not verified

Kubernetes, managed databases, TLS termination, and external connectors are not part of this release.
