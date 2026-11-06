# Changelog

All notable changes to RelayOps are documented here. The project follows semantic versioning while in alpha.

## [0.1.0-alpha] - 2026-11-06

First local alpha.

### Added

- Authentication: Argon2 passwords, hashed opaque sessions in HttpOnly cookies, expiry and logout revocation, login
  throttling, session-bound CSRF with Origin checks, safe role-aware redirects, organization registration, and
  account-scoped customer invitations.
- Organization and customer-account scoping across tickets, messages, knowledge and document bytes, retrieval,
  counts, runs and events, proposals, artifacts, exports, and actions.
- Customer portal, staff inbox with filters and live first-response targets, and ticket detail with internal notes,
  account context, receipts, links, and an evidence timeline.
- Versioned knowledge ingestion (Markdown/TXT) with local embeddings, lexical/dense/RRF retrieval sharing one
  authorization filter, and a retrieval inspector.
- A bounded LangGraph investigation runtime on a local Ollama model with six typed read tools, code-enforced budgets,
  one repair attempt, deadlines, routing constraints, deterministic verification, a review interrupt, and Postgres
  checkpoints.
- Durable jobs with leases, heartbeats, advisory locks, crash recovery, cancellation, retry from checkpoint, recorded
  replay, and comparison runs.
- Version-bound review (edit, approve, reject) and a unique action ledger with a transactional outbox for local
  actions; a simulated connector for failure-mode tests.
- Engineering board with duplicate candidates and ownership, incident constellations with distinct-account counts and
  review-gated confirmation, admin-only publishing of public incident summaries.
- Four executable playbooks with typed revisions and graph previews; immutable artifacts with verification state and
  Markdown/JSON exports; CSV exports for tickets and incidents.
- Evaluation harness: 180 labeled synthetic cases plus a challenge suite, rules/RAG/agent runners, offline gates, a
  measured live smoke report, and an Evaluations page.
- Synthetic TaskFlow Cloud world (five accounts, 52 documents, 128 historical tickets, 15 engineering issues,
  11 incidents, 8 deployments, and 837 hourly error-aggregate rows) plus an isolation organization with 2 documents.
- Make targets, CI (backend, frontend, offline evaluation, browser journey, hygiene, containers), and a verified
  container app profile.

### Known limitations

- Read-only MCP endpoint deferred (tokens only). No PDF ingestion or export. No business-hours calendar. No password
  reset. Human claim-support review pending.
