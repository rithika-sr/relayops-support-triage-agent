# 0004: Local actions through a unique ledger and outbox

Status: accepted

## Context

Approved actions must happen once, survive crashes, and must not be confused with email or external tracker writes.

## Decision

Default `ACTION_MODE=local`. The act node inserts an `action_ledger` row with unique `idempotency_key` and
`proposal_id`, performs local effects (customer-visible message, issue link or `LOCAL-n` handoff, incident link,
restricted escalation), and writes an outbox row in the same transaction. External connectors are disabled; a
deterministic simulated connector tests rejection, timeout-after-success (`unknown`, reconciled by marker), and
unreachable reconciliation without recreating.

## Consequences

- Re-running the act node after a crash returns the existing record.
- Replies never resolve tickets; status moves to `pending_customer`.
- A real external adapter would plug into the outbox path and reuse the unknown-outcome reconciliation.
