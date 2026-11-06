# 0013: GitHub Issues connector, limited to loopback hosts in this release

Status: superseded by [0015](0015-opt-in-live-github-profile.md)

## Context

Approved engineering handoffs should be mirrored to an issue tracker. Writing to a live tracker is an external
operation that affects people outside this system; a token in configuration is not authorization to do that.

## Decision

Implement the connector against the GitHub REST shape, delivered from the outbox after the local action commits.
Each issue body carries a hidden marker with the action's idempotency key. A timeout, 5xx, or lost response is
recorded as `unknown` and resolved by marker search, never by blind re-creation; retries back off and stop after
five attempts for an operator decision. The connector refuses any non-loopback base URL. Tests run against a local
GitHub-shaped HTTP service that can reject, fail, or drop responses.

## Consequences

- Live GitHub use stays pending until a separately authorized live operation; enabling it needs a code change
  reviewed for that purpose, not a setting.
- The local action stands regardless of the mirror's outcome, and the receipt says what happened remotely.
