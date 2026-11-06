# Diagrams

Seven views of the system, each drawn from the code it describes. CI renders every block on this page with a pinned
Mermaid CLI and fails on a syntax error (`scripts/render_diagrams.py`).

## 1. Components (flowchart)

What runs where. Everything is local: the model runs in Ollama on the same machine, and the only outbound
connector talks to loopback test services in this release.

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
  Fake["GitHub-shaped service<br/>(loopback only)"]
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

## 2. From ticket to customer reply (sequence)

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

## 3. Investigation run lifecycle (state)

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

## 4. Core records (entity relationship)

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

## 5. Claim verification pipeline (class)

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

## 6. Customer self-service (user journey)

What a customer does in the portal, and which product event each step records (`domain/events.py`).
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

## 7. Evaluation dataset by split (pie)

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
