# Architecture

## Components

| Process | Responsibility |
| --- | --- |
| Web (`frontend/`, Next.js 16, port 3020) | Landing, auth, staff workbench, customer portal. All data access goes through one typed client to same-origin `/api`, which Next rewrites to the API. |
| API (`backend/src/relayops/api`, FastAPI, port 8020) | Authentication, CSRF, request validation, and HTTP mapping. Routers call services only. Also serves the read-only MCP endpoint (`/mcp/`) and the signed ingestion webhook. |
| Worker (`backend/src/relayops/workers`) | Claims leased jobs, advances the LangGraph thread for a run, delivers the outbox (local topics, and the GitHub mirror to loopback test services). |
| Postgres 17 + pgvector (Docker, port 5440) | Domain records, knowledge chunks with tsvector and 768-d vectors, LangGraph checkpoints, run events, jobs, proposals, reviews, action ledger, outbox, audit. |
| Ollama (native, port 11434) | `qwen3:4b-instruct` for generation and `embeddinggemma` for embeddings, one inference at a time. |

## Backend layering

```
api/routers ──> services ──> repositories/scoped ──> models (SQLAlchemy)
                  │  ▲
                  │  └── tools/registry (agent read tools call the same services)
                  └── agents/graph (LangGraph) ── agents/llm (Ollama | labeled fixture)
domain/  pure rules: scope, policies, routes, binding, incidents, playbooks (no FastAPI imports)
core/    config, clock, db sessions, security primitives
```

- `domain/scope.Principal` is built only from a hashed session (or a hashed API token) plus a membership row.
- `repositories/scoped.py` applies `organization_id` to every tenant query and, for customers, `customer_account_id`
  plus customer-visible filters. Object reads outside scope return 404 so IDs cannot be probed.
- Services own transactions and audit records. No transaction is held open across model inference or HTTP.

## Investigation runtime

```
load_context ─> extract ─> precheck ─┬─> propose (records decided the route: selective path)
                                     └─> investigate ⟲ (≤4 turns, ≤6 tool calls) ─> propose
propose ─> draft_reply ─> verify ─> review ⏸ ─> act ─> audit_outcome
```

- **load_context** (code) snapshots the ticket revision, customer-visible messages, account plan and entitlements,
  response target, policy version, and the playbook configuration.
- **extract** (model) lists stated facts; recorded ticket fields override extraction.
- **precheck** (code) runs trusted lookups (known issues for the reported signature and version, reviewed incidents,
  this account's error aggregates, typed entitlements) and applies the ordered rules in `agents/policy.py`. On the
  selective path a deciding rule sets the route and investigation is skipped; otherwise (and always on the adaptive
  path) the run investigates. The decision and its explanation are recorded as a `trusted_lookup` event.
- **investigate** (model + tools) asks for a short observable purpose and up to two tool calls per turn. The
  dispatcher validates names and arguments against pydantic models with `extra="forbid"`, runs the tool in a short
  read transaction with the trusted context, and records each observation with a status (`ok`, `empty`, `stale`,
  `unavailable`, `unauthorized`, `failed`, `repeated`). A repeated identical call costs no budget; two repeats end
  investigation with `no_new_information`.
- **propose** (model) chooses a route; code then applies constraints: restricted tickets go to specialist review;
  issue links require a signature and affected-version match (otherwise a corrected link or a new handoff);
  incident links require a reviewed incident; disallowed routes fall back to specialist review. Computed facts
  (plan, entitlements, due time, affected-account counts) come from records.
- **draft_reply** (model) writes the customer reply from a customer-audience evidence view (a code-run retrieval
  with customer visibility filters) plus public evidence from the run. Security tickets use a fixed template.
- **verify** (code) persists proposal v1 with deterministic checks and claim-level support (`agents/claims.py`:
  sentence classification, typed entitlement and number checks, then the configured local verifier over cited
  passages only), and creates artifact versions. The verifier's model and digest are stored with the result.
- **review** calls LangGraph `interrupt()`. Nothing before it performs a non-idempotent effect; the proposal insert
  is keyed by `(run_id, version)`.
- **act** (code) executes the approved proposal through the action ledger (see below).

Each step is checkpointed with LangGraph's `PostgresSaver` on thread `thread_<run_id>` with synchronous durability.
If the worker dies mid-run, the job lease expires, another worker claims it, and `invoke(None)` resumes from the last
completed step. A session-level advisory lock keyed by run ID prevents two processes from advancing the same thread.

When the model output is invalid, the step gets one repair attempt per run; after that the investigation stops and
the run proposes a human specialist handoff with an `insufficient_evidence` verdict. When Ollama is unreachable the
run fails visibly (`model_unavailable` event) and can be retried from its checkpoint. When the deadline passes, the
run stops investigating and proposes a handoff. Cancellation stops future model, tool, and action work and does not
claim to undo completed effects.

## Events

Every node, model call, decision, tool call, tool result, proposal, review edit, and action is appended to
`run_events` with a per-run monotonic `seq` (allocated by `UPDATE ... RETURNING` on the run row). The UI follows a run
over SSE (`/api/investigations/{id}/stream`, resumable with `Last-Event-ID`) with polling as a fallback; a page reload
reconstructs the run, graph state, and evidence entirely from these records.

## Review and actions

- A review row stores the approved binding and its hash. Approval requires the latest pending version, matching
  expected version and payload hash, passing verification, no staleness (ticket revision, policy version, source
  currency), and an admin reviewer for restricted tickets. Concurrent approvals serialize on a row lock; exactly one
  succeeds.
- Approval enqueues a resume job. The act node locks the proposal, rechecks the binding against current state, and
  inserts an `action_ledger` row whose `idempotency_key` and `proposal_id` are unique, then performs the local effects
  and an outbox row in the same transaction. Re-running after a crash returns the existing record.
- Local effects: a customer-visible `TicketMessage` linked to the action; first-response time; ticket status
  `pending_customer` (never resolved by drafting or replying); plus an issue link, a new `LOCAL-n` engineering issue,
  an incident link, or a restricted escalation note depending on the action.
- With a GitHub Issues connection configured, an approved handoff also queues a `github.create_issue` outbox message.
  The connector (`services/github_connector.py`) refuses non-loopback hosts in this release, marks each issue with
  the action's idempotency key, records lost responses as `unknown`, and reconciles them by marker search with
  bounded, backed-off retries. `SimulatedIssueConnector` remains for unit-level failure tests.

## Knowledge and retrieval

Markdown, text, and PDF are accepted. PDF pages are read from the text layer, or with tesseract OCR when a page has
almost no text; each version stores a per-page extraction report. Text is chunked by heading (max 1,200 characters) and embedded before any rows are written. Each document version
has a content hash, validity window, visibility, component, product versions, and optional account scope. Lexical
(`ts_rank_cd`, not BM25), dense (exact cosine over pgvector), and RRF modes share one filter for organization,
account, audience, current version, document status, and validity. Scores get an authority boost (policy >
article/runbook/release note > historical case). Dense search only uses vectors whose `embedding_model` matches the
configured model; an index/model mismatch is reported in Settings. Generated drafts are never indexed as knowledge.

## Data model (main tables)

`organizations`, `customer_accounts`, `users`, `memberships`, `auth_sessions`, `login_attempts`, `invitations`,
`api_tokens`, `tickets`, `ticket_messages`, `knowledge_documents`, `document_versions`, `knowledge_chunks`,
`engineering_issues`, `ticket_issue_links`, `component_owners`, `deployments`, `error_aggregates`, `incidents`,
`incident_ticket_links`, `investigation_runs`, `run_events`, `jobs`, `proposals`, `reviews`, `action_ledger`, `outbox`,
`artifacts`, `artifact_versions`, `playbooks`, `playbook_revisions`, `audit_events`, `eval_reports`,
`instance_metadata`, `import_batches`, `connections`, `ingestion_receipts`, `saved_views`, `claim_annotations`,
`service_calendar_versions`, `product_events`, `experiments`, plus LangGraph's own `checkpoints*` tables. Most rows
carry `data_class` (operational, demo, test, unknown), set by the server. See [diagrams.md](diagrams.md) for an ER view.

## Trust boundaries

1. Browser to API: session cookie (HttpOnly, SameSite=Lax) plus a session-bound CSRF header and Origin check on every
   mutation; a custom header and Origin check guard login and registration.
2. API to data: every tenant read and write passes through scoped repositories or services that check membership.
3. Agent to data: the model only names tools and arguments; scope, budgets, routing constraints, verification, and
   writes are code.
4. Customer and retrieved text are wrapped as data in prompts and never treated as instructions.
5. MCP clients: a hashed `mcp:read` bearer token, re-resolved on every request; tools call the scoped services.
6. Inbound systems: a per-connection HMAC secret (stored encrypted), a timestamp window, and receipts keyed by the
   sender's event ID; the connection's server-side account map decides which account a ticket belongs to.

See [security.md](security.md) for details and [adr/](adr/) for the tradeoffs behind these choices.
