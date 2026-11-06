# Diagrams

Seven views of the system, each drawn from the code it describes, plus four supplementary views. CI renders every
Mermaid block in the README and docs with a pinned CLI (`@mermaid-js/mermaid-cli` 11.4.2) and fails on any error
(`scripts/render_diagrams.py`). Nothing here depicts infrastructure that is not implemented: there is no cloud
deployment, load balancer, or managed database.

## 1. System context

Who uses RelayOps and what it talks to. The model runs on the same machine; the tracker connector is limited to a
loopback test service unless an operator enables allow-listed `api.github.com` repositories (implemented, not yet
exercised against real GitHub).

```mermaid
flowchart TB
  Customer(["Customer users<br/>(portal)"])
  Staff(["Support, engineering, CS staff<br/>(staff app)"])
  Sender(["Other helpdesk or system<br/>(signed webhook, CSV/JSON import)"])
  Assistant(["MCP client<br/>(read-only token)"])
  RO["RelayOps<br/>one organization per tenant;<br/>operational or demo instance"]
  Model["Local model runtime<br/>Ollama on the same machine"]
  GH["Issue tracker<br/>loopback test service, or opt-in<br/>allow-listed api.github.com"]
  Customer -- "tickets, Help, approved replies" --> RO
  Staff -- "triage, review, approve" --> RO
  Sender -- "tickets (HMAC-signed)" --> RO
  Assistant -- "read tickets, runs, knowledge" --> RO
  RO -- "extraction, routing, drafts, claim checks, embeddings" --> Model
  RO -. "approved engineering handoffs" .-> GH
```

## 2. Components and containers

What runs where inside one installation.

```mermaid
flowchart LR
  subgraph Browser
    Staff[Staff app /app]
    Portal[Customer portal /portal]
  end
  subgraph Web["Next.js 16 (port 3020)"]
    Pages[Pages and components]
  end
  subgraph API["FastAPI (port 8020)"]
    Routers[Routers] --> Services[Services]
    Services --> Repos[Scoped repositories]
    MCP["Read-only MCP /mcp/"] --> Services
    Ingest["Signed webhook /api/ingest/..."] --> Services
  end
  subgraph Worker["Worker process"]
    Graph[LangGraph investigation] --> Tools[Typed tools]
    Outbox[Outbox delivery]
  end
  DB[("Postgres 17 + pgvector<br/>records, jobs, checkpoints, events")]
  Ollama["Ollama<br/>qwen3:4b-instruct, embeddinggemma"]
  Fake["GitHub-shaped test service (loopback)<br/>or opt-in api.github.com allowlist"]
  Staff --> Pages
  Portal --> Pages
  Pages -- "/api rewrite" --> Routers
  Repos --> DB
  Graph --> DB
  Tools --> Services
  Graph --> Ollama
  Services -- "embeddings" --> Ollama
  Outbox --> DB
  Outbox -. "approved handoffs" .-> Fake
```

## 3. Agent state flow

The LangGraph nodes for one investigation (`agents/graph.py`). The selective path takes the route from a typed
policy rule when the records decide it; otherwise both paths investigate adaptively.

```mermaid
stateDiagram-v2
  direction LR
  [*] --> load_context
  load_context --> extract: trusted ticket, account, plan, target
  extract --> precheck: reported facts (+ codes detected in text)
  precheck --> propose: selective path and a policy rule decides
  precheck --> investigate: adaptive path, or no rule decides
  investigate --> investigate: next tool call (max 4 turns, 6 calls)
  investigate --> propose: enough evidence, budget, repeats, or deadline
  propose --> draft_reply: route (code constraints applied)
  draft_reply --> verify: reply from customer-visible evidence
  verify --> review: checks + claim verdicts stored on proposal vN
  review --> review: reviewer edit (new version, re-verified)
  review --> act: approved exact version
  review --> audit_outcome: rejected
  act --> audit_outcome: action ledger (once) + outbox
  audit_outcome --> [*]
  note right of review
    Graph interrupt. Nothing customer-visible
    happens before approval.
  end note
```

## 4. End-to-end sequence: from ticket to customer reply

Nothing reaches the customer until a person approves the exact version that was checked.

```mermaid
sequenceDiagram
  autonumber
  actor C as Customer
  actor S as Support reviewer
  participant API
  participant W as Worker
  participant M as Local model
  participant DB as Postgres
  C->>API: POST /api/tickets
  API->>DB: ticket + message + ticket.created event
  S->>API: Start investigation (playbook)
  API->>DB: run + job (queued)
  W->>DB: claim job (FOR UPDATE SKIP LOCKED)
  W->>M: extract facts (structured output)
  W->>DB: trusted lookups (issues, incidents, entitlements)
  alt records decide the route (selective path)
    W->>W: route from policy rule
  else not decisive
    W->>M: next action (bounded tool calls)
  end
  W->>M: draft reply from cited, customer-visible evidence
  W->>W: verify: provenance, policy, typed facts, claim checks
  W->>DB: proposal v1 (awaiting review, checkpointed)
  S->>API: edit (new version re-verified) or approve exact hash
  API->>DB: review bound to payload, evidence, and ticket revision
  W->>DB: action ledger (once) + customer message + outbox
  C->>API: GET ticket: sees only the approved text
```

## 5. Entity relationships

A subset of the schema (Alembic migrations 0001–0007). Every row carries its organization, and most carry a
`data_class` (operational, demo, test, unknown) set by the server.

```mermaid
erDiagram
  ORGANIZATION ||--o{ CUSTOMER_ACCOUNT : has
  ORGANIZATION ||--o{ MEMBERSHIP : has
  CUSTOMER_ACCOUNT ||--o{ TICKET : opens
  TICKET ||--o{ TICKET_MESSAGE : contains
  TICKET ||--o{ INVESTIGATION_RUN : investigated_by
  INVESTIGATION_RUN ||--o{ PROPOSAL : drafts
  PROPOSAL ||--o{ REVIEW : decided_by
  PROPOSAL ||--o{ CLAIM_ANNOTATION : labeled_by
  PROPOSAL ||--o| ACTION_LEDGER : executes_once
  ACTION_LEDGER ||--o{ OUTBOX : emits
  KNOWLEDGE_DOCUMENT ||--o{ DOCUMENT_VERSION : versions
  DOCUMENT_VERSION ||--o{ KNOWLEDGE_CHUNK : indexed_as
  ORGANIZATION ||--o{ SERVICE_CALENDAR_VERSION : defines
  ORGANIZATION ||--o{ PRODUCT_EVENT : records
  ORGANIZATION ||--o{ CONNECTION : configures
  CONNECTION ||--o{ INGESTION_RECEIPT : receives
  TICKET {
    string id
    string data_class
    string source_kind
    datetime first_response_due_at
    json target_policy
  }
  PROPOSAL {
    int version
    string payload_hash
    json verification
    string status
  }
  ACTION_LEDGER {
    string idempotency_key
    string status
    json receipt
  }
```

## 6. Deployment and trust boundaries

The supported deployment is a single host. Ports are the defaults; Postgres binds to 127.0.0.1. Each arrow names
the control at that boundary.

```mermaid
flowchart LR
  subgraph Host["One machine (supported deployment: local or a single host you control)"]
    subgraph Pub["Bound to localhost by default"]
      Web["Next.js :3020<br/>(demo :3030)"]
      API["FastAPI :8020<br/>(demo :8030)"]
    end
    Worker["Worker process(es)"]
    subgraph Docker["Docker"]
      PG[("Postgres :5440 on 127.0.0.1<br/>relayops_operational | demo DB | eval DBs")]
    end
    Ollama["Ollama :11434"]
    Local[".env and .local/ (git-ignored):<br/>secrets, demo credentials"]
  end
  Browser["Browser"] -- "session cookie + CSRF header + Origin check" --> Web
  Web -- "/api rewrite (same origin)" --> API
  Sender["Signed sender"] -- "HMAC, 5-min window, receipts" --> API
  MCPc["MCP client"] -- "bearer mcp:read token" --> API
  API -- "scoped by organization and account" --> PG
  Worker --> PG
  Worker --> Ollama
  API --> Ollama
  Worker -. "loopback, or allow-listed api.github.com when enabled" .-> GH["Tracker"]
```

## 7. Adoption-event flow

How customer activity becomes Customer Success views (`domain/events.py`, `services/success.py`). Demo and test
records never reach an operational instance's numbers.

```mermaid
flowchart LR
  subgraph Sources["Recorded by the app (server-side)"]
    S1["sign-in"] --> E
    S2["ticket created"] --> E
    S3["reply published (after approval)"] --> E
    S4["Help search / article view / feedback / contact"] --> E
    S5["experiment exposure"] --> E
    S6["admin event import (dry run first)"] --> E
  end
  E[("product_events<br/>schema v1, typed properties,<br/>unique event_id per org, data_class")]
  E --> F{"data class allowed?<br/>operational instance: operational only"}
  F -- yes --> V1["Onboarding steps"]
  F -- yes --> V2["Account adoption and friction"]
  F -- yes --> V3["Retention cohorts<br/>(pending until reachable)"]
  F -- yes --> V4["Opportunity rules"]
  F -- yes --> V5["Experiment results<br/>(hidden below minimum)"]
  F -- "no (demo, test, unknown)" --> X["excluded and counted as excluded"]
```

## Supplementary views

### Investigation run lifecycle (state)

Statuses from `services/runs.py` (`ACTIVE`, `TERMINAL`).

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> running: worker claims job
  running --> awaiting_review: proposal created
  running --> failed: model unavailable or worker error after retries
  awaiting_review --> executing: approved (binding still matches)
  awaiting_review --> rejected: reviewer rejects
  awaiting_review --> awaiting_review: reviewer edits (new version)
  executing --> completed: action succeeded or reconciled
  executing --> failed: action refused or failed
  queued --> cancelled
  running --> cancelled
  awaiting_review --> cancelled
  completed --> [*]
  failed --> [*]
  rejected --> [*]
  cancelled --> [*]
```

### Claim verification types (class)

`agents/claims.py` and `agents/verification.py`. Method and verdict stay separate so a typed rule, a model
judgment, and a human label are never presented as the same thing.

```mermaid
classDiagram
  class Claim {
    +str text
    +str kind  social|request|hypothesis|procedural|factual
    +str verdict  supported|contradicted|insufficient_evidence|unavailable|not_a_claim
    +str method  typed_entitlement|typed_number|semantic_model|not_run|none
    +list evidence_ids
    +str detail
  }
  class TypedCheck {
    +entitlement(entity, polarity, plan)
    +number(value, unit, cited spans)
  }
  class SemanticVerifier {
    +str model
    +str digest
    +judge(claim, cited spans) Claim
  }
  class Verification {
    +list checks
    +list claims
    +int uncertain_claims
    +dict claim_verifier
    +status passed|failed
  }
  class ClaimAnnotation {
    +str claim_sha256
    +str verdict
    +str annotator_key
    +immutable
  }
  Verification "1" o-- "*" Claim
  TypedCheck ..> Claim : decides when records settle it
  SemanticVerifier ..> Claim : otherwise, cited spans only
  ClaimAnnotation ..> Claim : human label bound to exact text
```

### Customer self-service (user journey)

Scores are the author's expectation of effort, not measurements.

```mermaid
journey
  title Finding an answer before opening a ticket
  section Search
    Sign in (user.signed_in): 4: Customer
    Search Help (help.searched): 4: Customer
  section Read
    Open an article (article.viewed): 4: Customer
    Say whether it helped (article.feedback): 3: Customer
  section Escalate
    Contact support from the article (help.escalated): 3: Customer
    Reviewed reply arrives (reply.published): 5: Customer, Support
```

### Evaluation dataset by split (pie)

Case counts from the committed split manifests: `evals/datasets/split_manifest.json` (main set: dev 72,
validation 54, test 54, challenge 6) plus `hard_split_manifest.json` (hard slice: dev 12, validation 9, test 9).
The test splits are frozen and have not been run.

```mermaid
pie showData
  title Evaluation cases by split (main + hard)
  "dev" : 84
  "validation" : 63
  "test (frozen)" : 63
  "challenge" : 6
```
