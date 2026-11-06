# RelayOps

RelayOps is a local-first support-to-engineering operations app. A customer reports a problem in a portal; a support
operator launches a bounded investigation that runs on a local model; the agent gathers authorized evidence with
typed read tools, proposes a route and a customer reply or engineering handoff, and pauses for human review. The
reviewer edits or approves an exact version, the approved action runs once, and every step stays inspectable.

This is a **local alpha**. All companies, tickets, documents, and metrics in the demo world are synthetic.
Approved actions are local to the app: an approved reply becomes a customer-visible message in RelayOps (not an
email), and an approved handoff creates or links a local engineering record (not a GitHub or Jira write).

## What it does

- **Account-aware investigation.** One LangGraph workflow (load context, extract, adaptive investigation, propose,
  draft reply, verify, review interrupt, act, record outcome) runs on `qwen3:4b-instruct` through Ollama with
  schema-constrained JSON. Code enforces 4 investigation turns, 6 read-tool calls, one repair attempt, bounded
  outputs, and a wall-clock deadline.
- **Six typed read tools.** `search_knowledge`, `find_similar_cases`, `search_engineering_issues`,
  `get_incident_snapshot`, `get_recent_deployments`, `get_error_aggregates`. Scope comes from a server-built trusted
  context; argument schemas forbid extra fields, so the model cannot pick a tenant, account, role, or destination.
- **Evidence and verification.** Each observation is stored with its source version, content hash, and snapshot
  hash. Deterministic checks cover provenance, visibility, source currency, plan entitlements, internal identifiers,
  causal and outage claims, and issue/incident links. Lexical overlap is shown as a signal and labeled as not
  semantic proof.
- **Version-bound review.** Approval binds organization and account, reviewer, ticket revision, proposal version,
  action, destination, payload hash, evidence hash, and policy version. Edits create a new version; a new customer
  message makes older drafts stale; execution rechecks the binding.
- **Durable runtime.** Postgres holds domain data, pgvector embeddings, LangGraph checkpoints, sequenced run events,
  leased jobs, proposals, reviews, the action ledger, and the outbox. A crashed worker resumes from the last
  checkpoint; a per-run advisory lock prevents concurrent advancement.
- **Diagnostics and incidents.** Synthetic deployments and hourly error aggregates feed a timestamped evidence
  timeline that separates customer reports, trusted records, computed signals, and hypotheses. Incident
  constellations group tickets by component, signature, version, and time window with distinct-account counts and
  require review before they become incidents.
- **Playbooks, artifacts, replay.** Four typed playbooks (how-to, bug, feature, incident) run on the same runtime.
  Artifacts keep immutable versions with hashes and verification state and export as Markdown or JSON. Recorded
  replay re-presents a finished run without executing anything; a comparison run is new and needs fresh review.
- **Evaluation.** 180 labeled synthetic cases split by root family, a separate challenge suite, and runners for
  rules/lexical, single-pass RAG, and the bounded agent. Results report denominators and leave unrun cases unrun.

## Architecture at a glance

```
browser ──> Next.js (3020) ──/api rewrite──> FastAPI (8020) ──> services ──> scoped repositories ──> Postgres+pgvector (5440)
                                                   │                                   ▲
                                                   └── jobs ──> worker ── LangGraph ───┘── checkpoints, events, ledger
                                                                   └── Ollama (11434): qwen3:4b-instruct, embeddinggemma
```

Routers call services; services enforce rules and transactions; repositories apply organization and customer-account
scope to every query; agent tools call the same services. See [docs/architecture.md](docs/architecture.md).

## Quick start

Prerequisites: macOS or Linux, Docker, [uv](https://docs.astral.sh/uv/), Node 24, and [Ollama](https://ollama.com).

```bash
make setup                       # .env with fresh secrets, Python 3.12 env, npm deps, Postgres, migrations
ollama pull qwen3:4b-instruct
ollama pull embeddinggemma
make seed                        # synthetic world + demo logins in .local/demo-credentials.json (git-ignored)
make dev                         # API :8020, worker, web :3020
make demo                        # health check and walkthrough
```

Open http://localhost:3020 and sign in with an account from `.local/demo-credentials.json`:
`admin@relayops.local`, `support@relayops.local`, or `customer@northstar.local`. Passwords are generated on first
seed and stored hashed in the database; they are never committed or shown in the UI.

## Verification

| Command | What it runs |
| --- | --- |
| `make test-offline` | ruff, mypy, pytest against real Postgres with the labeled fixture provider, ESLint, TypeScript, Vitest |
| `make test-live` | Real Ollama: model presence, 768-d embeddings, structured output, a tool-driven run to review |
| `make e2e` | Playwright journey against the running stack: portal ticket, investigation, edit, approve, customer sees reply |
| `make eval-offline` | Dataset validation, rules baseline, adversarial challenge invariants, regression gate |
| `make eval-live-smoke` | Six demos plus one validation case per category for all three systems on the local model |
| `make check-repo` | Secret patterns, tracked local-only files, documentation links |

CI runs backend, frontend, offline evaluation, a browser journey with the fixture provider, repository hygiene, and
container builds. CI never calls a paid model and does not assess live model quality.

## Documentation

- [Architecture](docs/architecture.md) and [decisions](docs/adr/)
- [Development](docs/development.md): setup, commands, test profiles, troubleshooting
- [API](docs/api.md) and [security model](docs/security.md)
- [Evaluation](docs/evaluation.md): methodology and measured results
- [Demo walkthrough](docs/demo.md) and [deployment profiles](docs/deployment.md)

## Limitations

- Local alpha on synthetic data; not validated for production use.
- A 4B local model makes routing and drafting mistakes; human review is required and is the semantic check.
- Lexical overlap is not entailment; claim support is not verified automatically, and no human claim annotations
  have been recorded yet.
- Response targets use 24/7 elapsed hours; there is no business-hours calendar.
- External connectors are disabled; a simulated adapter exists only for failure-mode tests.
- Read-only MCP endpoint at `/mcp/` (streamable HTTP) for `mcp:read` tokens; see ADR 0008.
- PDF ingestion and PDF export are not implemented.

## License

MIT. See [LICENSE](LICENSE). Third-party packages keep their own licenses (see the lockfiles).
