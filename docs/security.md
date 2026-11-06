# Security and authorization

## Authentication

- Passwords: Argon2id via `argon2-cffi` (minimum 12 characters). Unknown emails are verified against a dummy hash so
  timing and the error message match a wrong password.
- Sessions: 32 random bytes (`secrets.token_urlsafe`), stored only as SHA-256 digests, sent as the `relayops_session`
  cookie (HttpOnly, SameSite=Lax, `Secure` when `RELAYOPS_COOKIE_SECURE=true`). Default lifetime 12 hours; logout
  revokes the row server-side, and revoked or expired sessions are rejected.
- Local HTTP: cookies are not `Secure` on `http://localhost`; set `RELAYOPS_COOKIE_SECURE=true` behind HTTPS.
- Throttling: 5 failed attempts per email or 20 per client IP within 15 minutes returns 429 with `Retry-After`.
- CSRF: `relayops_csrf` (readable cookie) holds an HMAC of the session token; every mutation must echo it in
  `X-CSRF-Token` and, when present, send an allowed `Origin`. Login and registration require `X-Requested-With:
  relayops` plus the Origin check, which forces a CORS preflight cross-site.
- Redirects: only relative paths in the role's area (`/app` for staff, `/portal` for customers) are honored.
- Registration always creates a new organization owned by the registrant. Joining an existing organization requires
  an admin-issued invitation, which only grants the `customer` role on one customer account. Role or organization
  fields in a request body are ignored.

## Authorization model

| Role | Scope |
| --- | --- |
| admin | Everything in its organization, including audit, evaluations, members, invitations, tokens, playbook revisions, and publishing incidents to customers |
| support | Tickets, investigations, evidence, reviews, handoffs, incidents, knowledge, artifacts in its organization |
| customer | Its own account's tickets and customer-visible messages, public knowledge (organization-wide or for its account), and incidents an admin has published |

Enforcement points: scoped query builders (metadata, lists, counts), document bytes, retrieval filters, run events and
SSE, proposals, artifacts and exports, CSV list exports, and action execution. A customer principal cannot exist
without a customer account. Object reads outside scope return 404. Restricted (security-sensitive) tickets require
an admin reviewer.

## Agent boundaries

- Tool arguments are pydantic models with `extra="forbid"`; organization, account, and as-of time come from the
  trusted context built from the persisted run.
- Tools run fixed, allowlisted queries over synthetic records. No shell, SQL, or customer code is executed.
- The customer reply is drafted from a customer-audience evidence view; verification fails a draft that cites
  internal evidence, names internal issue keys, owner teams, or other customers, asserts a root cause, or claims a
  confirmed outage without a reviewed incident.
- Prompts mark customer and retrieved text as untrusted data. The challenge suite includes prompt injection, an
  injected historical case, cross-tenant lexical matches, unverified P1 claims, and security reports.

## API tokens

Admins can create read-scoped tokens (`mcp:read`). Plaintext is shown once; only the SHA-256 digest is stored;
revocation is immediate. Bearer tokens are rejected by every REST endpoint, so a read token cannot perform
mutations. The MCP endpoint that would accept them is deferred and not exposed.

## Secrets and local files

`make setup` writes `.env` (mode 0600) with a random Postgres password and session secret. `make seed` writes demo
passwords to `.local/demo-credentials.json` (mode 0600). `.env`, `.local/`, `.claude/`, and `CLAUDE.md` are
git-ignored, and `scripts/check_repo.py` fails CI if such files are tracked or credential patterns appear.

## Known gaps

- No password reset or MFA.
- Rate limiting is per process and database-backed; there is no global edge limiter.
- The app has not had an external security review.

Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).
