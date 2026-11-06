# API

The API is served under `/api` (FastAPI). Interactive schema: `http://localhost:8020/api/docs`. The browser reaches
it through the web origin's `/api` proxy.

## Conventions

- Auth: session cookie `relayops_session`. Mutations need `X-CSRF-Token` (value of the `relayops_csrf` cookie) and
  an allowed `Origin`. Login, registration, and invitation acceptance need `X-Requested-With: relayops`.
- Bearer tokens are rejected by all REST endpoints (401). They are accepted only by the MCP endpoint (`/mcp/`).
- Every response carries `X-Request-ID`. `GET /api/health` is liveness; `GET /api/ready` is readiness (503 with the
  failing check).
- Errors: `{"detail": "...", "errors": [{"field", "message"}]?, "code"?}` with 401 (sign in), 403 (role), 404 (not
  found or out of scope), 409 (conflict or stale state), 422 (validation), 429 (throttled), 503 (`model_unavailable`).

## Endpoints

| Method and path | Role | Purpose |
| --- | --- | --- |
| `POST /auth/login` | anyone | `{email, password, next?}` → user and safe `redirect_to` |
| `POST /auth/register` | anyone | Create a new organization and its admin |
| `POST /auth/accept-invitation` | anyone | `{token, name, password}` → customer membership |
| `POST /auth/logout` | signed in | Revoke the session |
| `GET /auth/me` | signed in | Principal, organization, account |
| `GET /tickets` | any | Search and filter (`q, queue, status, priority, account_id, component, assignee, sort, page, page_size`); customers see their account only |
| `POST /tickets/{id}/assign`, `POST /tickets/bulk` | staff | Assign; bulk status/priority/assignee (never replies) |
| `GET /home`, `GET /staff`, `GET/POST/DELETE /views` | staff | Home queues; assignable staff; saved views |
| `POST /tickets` | any | Create; customers always file on their own account; `external_event_id` deduplicates replayed intake |
| `GET /tickets/{id}` | any | Messages (customers: customer-visible only); staff also get account context, runs, proposals, actions, links |
| `POST /tickets/{id}/messages` | any | Customer reply (bumps revision) or staff internal note |
| `PATCH /tickets/{id}` | staff | Status, priority, component, version, error code |
| `GET /tickets/export.csv` | staff | Scoped CSV |
| `GET /tickets/{id}/timeline` | staff | Evidence timeline lanes |
| `GET /accounts`, `GET /overview` | any / staff | Accounts in scope; computed overview counts |
| `GET /knowledge`, `GET /knowledge/{id}` | any | Scoped documents and versions |
| `GET /knowledge/{id}/versions/{n}/raw` | any | Document bytes with `X-Content-Hash` (scoped) |
| `POST /knowledge` | staff | Multipart upload (`.pdf`, `.md`, `.txt`) with metadata; same slug = new version; PDFs return a per-page extraction report |
| `POST /knowledge/{id}/status`, `POST /knowledge/inspect` | staff | Status change; retrieval inspector |
| `POST /tickets/{id}/investigations` | staff | Start a run `{playbook_key?, retrieval_mode?}` |
| `GET /investigations`, `GET /investigations/{id}` | staff | List; detail with graph, events, evidence, proposals, actions |
| `GET /investigations/{id}/events?after=`, `GET /investigations/{id}/stream` | staff | Polling and SSE (`Last-Event-ID`) |
| `POST /investigations/{id}/cancel`, `/retry`, `/replay`, `/compare` | staff | Lifecycle operations |
| `POST /proposals/{id}/edit` | staff | `{customer_reply, expected_version}` → new version |
| `POST /proposals/{id}/approve` | staff | `{expected_version, expected_payload_hash, acknowledge_uncertain_claims?}`; admin required for restricted tickets; 409 when uncertain claims are not acknowledged |
| `POST /proposals/{id}/claims/{n}/annotations`, `GET /proposals/{id}/annotations` | staff | Human claim labels `{verdict, claim_sha256, note?}`; latest per annotator, disagreements flagged |
| `GET /annotations/export`, `POST /annotations/import`, `GET /annotations/stats` | staff / admin / staff | Label export, import (dry run default), agreement (pending without labels) |
| `POST /proposals/{id}/reject` | staff | `{expected_version, note?}` |
| `GET /engineering/board`, `GET /engineering/issues/{id}` | staff | Board, duplicate candidates, ownership; issue detail |
| `GET /incidents`, `GET /incidents/{id}` | any | Customers: published incidents only, public summary projection |
| `GET /incidents/candidates?window_hours=` | staff | Deterministic constellations |
| `POST /incidents/candidates/{key}/confirm` | staff | Review step; `expected_ticket_ids` must match current membership |
| `PATCH /incidents/{id}`, `POST /incidents/{id}/summary`, `GET /incidents/export.csv` | staff | Update (publishing is admin-only), summary artifact, CSV |
| `GET /artifacts`, `GET /artifacts/{id}` | staff | Versions with hashes and verification |
| `POST /artifacts/{id}/versions`, `POST /artifacts/{id}/revalidate` | staff | Edit (marks verification stale), re-verify |
| `GET /artifacts/{id}/export?format=md|json|pdf` | staff | Exports (PDF through a fixed template; demo records bannered) |
| `GET /playbooks`, `GET /playbooks/{key}`, `POST /playbooks/{key}/revisions` | staff / admin | Typed playbooks |
| `GET /audit` | admin | Audit history (`action` prefix, `outcome`) |
| `GET /evaluations`, `GET /evaluations/{id}`, `POST /evaluations/import` | admin | Evaluation reports from `evals/results` |
| `GET /settings/health`, `/policy`, `/connectors` | staff / any | Model and dependency health, policy tables, connector mode |
| `GET/POST /settings/members`, `/invitations`, `/tokens`, `POST /settings/tokens/{id}/revoke` | admin | Organization administration |
| `GET /settings/calendars`, `POST /settings/calendars`, `POST /settings/calendars/deactivate`, `POST /settings/calendars/preview` | staff / admin / admin / staff | Versioned service calendars and due-time preview |
| `POST /imports/preview`, `POST /imports`, `GET /imports` | staff | CSV/JSON ticket import: dry run, commit by `expected_sha256`, history |
| `GET /integrations`, `POST /integrations/webhooks`, `POST /integrations/github`, `POST /integrations/{id}/test`, `/rotate-secret`, `/enable`, `/disable`, `GET /integrations/{id}/receipts` | admin | Connections; GitHub targets must be loopback in this release |
| `POST /ingest/webhooks/{connection_id}` | signed sender | `X-RelayOps-Timestamp`, `X-RelayOps-Signature: sha256=…` over `<timestamp>.<raw body>`; no session or CSRF |
| `GET /portal/help/search?q=`, `GET /portal/help/articles/{id}`, `POST /portal/help/articles/{id}/feedback`, `POST /portal/help/contact`, `GET /portal/onboarding` | customer | Self-service Help and Getting started |
| `GET /success/accounts`, `/success/accounts/{id}/onboarding`, `/success/retention`, `/success/opportunities` | staff | Customer Success views (instance data class only) |
| `POST /events/import` | admin | Versioned product events (dry run default, deduplicated by `event_id`) |
| `GET /experiments`, `POST /experiments`, `POST /experiments/{id}/start|stop` | staff / admin | Help-ranking experiments with pre-registered minimums |

## MCP

`/mcp/` serves MCP over streamable HTTP (stateless, JSON responses) with the official SDK. Send
`Authorization: Bearer <mcp:read token>`. Tools: `search_knowledge`, `list_open_tickets`, `get_ticket`,
`get_investigation`, `list_approved_artifacts`, all annotated read-only. See ADR 0008.

## Run events

`run_events` rows have `seq`, `kind`, `node`, `payload`. Kinds include `run_queued`, `node_started`,
`node_completed`, `model_call`, `decision`, `tool_call`, `tool_result`, `proposal_created`, `awaiting_review`,
`proposal_edited`, `action_result`, `run_finished`, `cancel_requested`, `run_cancelled`, `model_unavailable`,
`run_failed`, `retry_requested`, and for recorded replays `replay_started`/`replay_finished` (replayed events carry
`replayed_from_seq`).
