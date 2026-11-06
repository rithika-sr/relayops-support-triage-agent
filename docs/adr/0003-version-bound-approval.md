# 0003: Approval binds an exact version and is rechecked before execution

Status: accepted

## Context

A reviewer approves what they read. Between approval and execution the ticket, the draft, the evidence, or the policy
can change, and two reviewers can approve at once.

## Decision

A review stores a binding (organization, account, reviewer, ticket and revision, proposal and version, action,
destination, payload hash, evidence hash, policy version) and its hash. Approval requires the latest pending version
with matching expected version and payload hash, passing verification, and no staleness. Execution locks the
proposal, recomputes the binding against current state, and refuses on any mismatch. Edits create new proposal
versions; older versions become `superseded`.

## Consequences

- Concurrent approvals serialize on a row lock; exactly one succeeds.
- A customer message during review makes the draft stale; the reviewer edits (which re-binds to the current
  revision) or starts a new run.
