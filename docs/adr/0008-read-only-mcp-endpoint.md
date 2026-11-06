# 0008: Read-only MCP endpoint over streamable HTTP

Status: accepted (supersedes 0007)

## Context

Admins could already mint hashed `mcp:read` tokens, but nothing accepted them. Assistants that speak MCP need a
way to read ticket status, investigation outcomes, knowledge, and saved artifacts without a browser session and
without any ability to change records.

## Decision

Mount the official SDK's `MCPServer` (mcp 2.3.0; FastMCP was renamed in 2.x) at `/mcp/` inside the API process,
using stateless streamable HTTP with JSON responses.

- A `TokenVerifier` resolves the bearer token through the same hashed API-token table on every request. Only
  staff-owned tokens with `mcp:read` are accepted. Session cookies are not credentials here.
- Each tool re-resolves the token to a `Principal` and calls the existing scoped services, so organization scope
  and restricted-ticket rules are the web app's rules. Missing or cross-organization IDs return a tool error.
- Five tools, all annotated `readOnlyHint=true, destructiveHint=false`: `search_knowledge` (lexical, so no
  model call in the request path), `list_open_tickets`, `get_ticket`, `get_investigation`,
  `list_approved_artifacts`. No resources, prompts, or write tools.
- Host and Origin headers are validated against the configured API and web origins (DNS-rebinding protection).
- The SDK's session manager runs inside the API lifespan; a fresh one is built for each lifespan start.

## Consequences

- Tests cover missing, invalid, revoked, and cookie-only credentials; scope minting; cross-organization reads;
  unknown tool names; REST rejecting bearer tokens; and the SDK's own client over a real socket.
- Tokens are long-lived bearer secrets with no expiry yet. Rotation is manual (revoke and mint).
- There is no OAuth authorization server. The protected-resource metadata URL advertised in 401 responses has no
  authorization server behind it; clients must be configured with a token directly.
