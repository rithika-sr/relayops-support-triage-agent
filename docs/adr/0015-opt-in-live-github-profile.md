# 0015: An opt-in live GitHub profile beside the local contract-test profile

Status: accepted (supersedes 0013)

## Context

A connector that only accepts loopback hosts proves the delivery contract against a local test service but
cannot be used with GitHub. Enabling remote writes must still be an operator decision made on the server, not
something a token or an admin's form submission can do.

## Decision

Every GitHub connection has a target profile, checked when it is created and again before every request:

- `local_contract_test`: loopback hosts only. The test suite and local demos use this.
- `github_live`: only `https://api.github.com` (configurable host, exact match: no other scheme, port, path, or
  subdomain), only when `RELAYOPS_GITHUB_LIVE_ENABLED=true`, and only for repositories in the server-side
  `RELAYOPS_GITHUB_REPO_ALLOWLIST`. Removing a repository from the allowlist stops delivery before any request
  and records `not_sent`.

Everything else from 0013 stands: delivery from the outbox after the approved local action commits, an
idempotency marker in the issue body, `unknown` outcomes reconciled by marker search, bounded backed-off retries,
the token encrypted at rest and redacted from recorded errors.

## Consequences

- The live path is implemented and tested with a mock transport that stands in for `api.github.com`. It has not
  been exercised against real GitHub; that needs a separately authorized repository and token.
- Marker search lists issues with the `relayops` label (up to 1,000); it does not use GitHub search.
