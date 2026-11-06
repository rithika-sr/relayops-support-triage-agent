# 0007: Read-only MCP endpoint deferred

Status: accepted for this release

## Context

A scoped, read-only MCP endpoint (knowledge search, ticket status, investigation summaries, approved artifacts) was
planned as a stretch module after the core journey.

## Decision

Ship the token half only: admins can create read-scoped (`mcp:read`) tokens, shown once and stored as hashes, and
revoke them. All REST endpoints reject bearer tokens, so a read token cannot mutate anything. The MCP server itself is
not exposed in this release, and the Settings page says so.

## Consequences

- No connector success is shown or claimed.
- Implementing the endpoint means adding a transport that resolves the token to a principal and calls the existing
  scoped services, plus scope, revocation, and cross-organization tests.
