# API

The API is served under `/api` (FastAPI). Interactive schema: `http://localhost:8020/api/docs`. The browser reaches
it through the web origin's `/api` proxy.

## Conventions

- Auth: session cookie `relayops_session`. Mutations need `X-CSRF-Token` (value of the `relayops_csrf` cookie) and
  an allowed `Origin`. Login, registration, and invitation acceptance need `X-Requested-With: relayops`.
- Bearer tokens are rejected by all REST endpoints (401).
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
| `GET /tickets` | any | Search and filter (`q, status, priority, account_id, component, page, page_size`); customers see their account only |
| `POST /tickets` | any | Create; customers always file on their own account; `external_event_id` deduplicates replayed intake |
| `GET /tickets/{id}` | any | Messages (customers: customer-visible only); staff also get account context, runs, proposals, actions, links |
| `POST /tickets/{id}/messages` | any | Customer reply (bumps revision) or staff internal note |
| `PATCH /tickets/{id}` | staff | Status, priority, component, version, error code |
| `GET /tickets/export.csv` | staff | Scoped CSV |
| `GET /tickets/{id}/timeline` | staff | Evidence timeline lanes |
| `GET /accounts`, `GET /overview` | any / staff | Accounts in scope; computed overview counts |
| `GET /knowledge`, `GET /knowledge/{id}` | any | Scoped documents and versions |
| `GET /knowledge/{id}/versions/{n}/raw` | any | Document bytes with `X-Content-Hash` (scoped) |
| `POST /knowledge` | staff | Multipart upload (`.md`/`.txt`) with metadata; same slug = new version |
| `POST /knowledge/{id}/status`, `POST /knowledge/inspect` | staff | Status change; retrieval inspector |
| `POST /tickets/{id}/investigations` | staff | Start a run `{playbook_key?, retrieval_mode?}` |
| `GET /investigations`, `GET /investigations/{id}` | staff | List; detail with graph, events, evidence, proposals, actions |
| `GET /investigations/{id}/events?after=`, `GET /investigations/{id}/stream` | staff | Polling and SSE (`Last-Event-ID`) |
| `POST /investigations/{id}/cancel`, `/retry`, `/replay`, `/compare` | staff | Lifecycle operations |
| `POST /proposals/{id}/edit` | staff | `{customer_reply, expected_version}` → new version |
| `POST /proposals/{id}/approve` | staff | `{expected_version, expected_payload_hash}`; admin required for restricted tickets |
| `POST /proposals/{id}/reject` | staff | `{expected_version, note?}` |
| `GET /engineering/board`, `GET /engineering/issues/{id}` | staff | Board, duplicate candidates, ownership; issue detail |
| `GET /incidents`, `GET /incidents/{id}` | any | Customers: published incidents only, public summary projection |
| `GET /incidents/candidates?window_hours=` | staff | Deterministic constellations |
| `POST /incidents/candidates/{key}/confirm` | staff | Review step; `expected_ticket_ids` must match current membership |
| `PATCH /incidents/{id}`, `POST /incidents/{id}/summary`, `GET /incidents/export.csv` | staff | Update (publishing is admin-only), summary artifact, CSV |
| `GET /artifacts`, `GET /artifacts/{id}` | staff | Versions with hashes and verification |
| `POST /artifacts/{id}/versions`, `POST /artifacts/{id}/revalidate` | staff | Edit (marks verification stale), re-verify |
| `GET /artifacts/{id}/export?format=md|json` | staff | Exports |
| `GET /playbooks`, `GET /playbooks/{key}`, `POST /playbooks/{key}/revisions` | staff / admin | Typed playbooks |
| `GET /audit` | admin | Audit history (`action` prefix, `outcome`) |
| `GET /evaluations`, `GET /evaluations/{id}`, `POST /evaluations/import` | admin | Evaluation reports from `evals/results` |
| `GET /settings/health`, `/policy`, `/connectors` | staff / any | Model and dependency health, policy tables, connector mode |
| `GET/POST /settings/members`, `/invitations`, `/tokens`, `POST /settings/tokens/{id}/revoke` | admin | Organization administration |

## Run events

`run_events` rows have `seq`, `kind`, `node`, `payload`. Kinds include `run_queued`, `node_started`,
`node_completed`, `model_call`, `decision`, `tool_call`, `tool_result`, `proposal_created`, `awaiting_review`,
`proposal_edited`, `action_result`, `run_finished`, `cancel_requested`, `run_cancelled`, `model_unavailable`,
`run_failed`, `retry_requested`, and for recorded replays `replay_started`/`replay_finished` (replayed events carry
`replayed_from_seq`).
