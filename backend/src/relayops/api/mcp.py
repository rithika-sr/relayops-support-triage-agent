"""Read-only MCP endpoint over streamable HTTP (official `mcp` SDK, MCPServer).

Authentication is a RelayOps API token with the `mcp:read` scope, sent as a bearer token. Every request
re-resolves the token, so revocation takes effect immediately. Tools run as the token owner's principal
through the same scoped services the web app uses; nothing here writes records (apart from the token's
last-used time). Restricted security tickets are visible only to admin-owned tokens.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import AnyHttpUrl
from sqlalchemy import select

from relayops.core.config import get_settings
from relayops.core.db import session_scope
from relayops.domain.scope import AccessDenied, NotFound, Principal
from relayops.models import InvestigationRun, Proposal, Ticket
from relayops.repositories import scoped
from relayops.services import artifacts, retrieval
from relayops.services import auth as auth_service
from relayops.services import tickets as ticket_service

SCOPE = "mcp:read"
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


class RelayTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        def check() -> AccessToken | None:
            with session_scope() as db:
                p = auth_service.resolve_api_token(db, token)
                if p is None or not p.is_staff or SCOPE not in p.scopes:
                    return None
                return AccessToken(
                    token=token,
                    client_id=p.membership_id,
                    scopes=sorted(p.scopes),
                    subject=p.user_id,
                    resource=_resource_url(),
                )

        return await anyio.to_thread.run_sync(check)


def _resource_url() -> str:
    return get_settings().api_origin.rstrip("/") + "/mcp"


def _run[T](fn: Callable[[Any, Principal], T]) -> T:
    tok = get_access_token()
    if tok is None:
        raise ToolError("not authenticated")
    with session_scope() as db:
        p = auth_service.resolve_api_token(db, tok.token)
        if p is None or SCOPE not in p.scopes:
            raise ToolError("token revoked or missing the mcp:read scope")
        try:
            return fn(db, p)
        except (NotFound, AccessDenied) as exc:
            raise ToolError(str(exc)) from exc


async def _call[T](fn: Callable[[Any, Principal], T]) -> T:
    return await anyio.to_thread.run_sync(_run, fn)


def _ticket_out(t: Ticket) -> dict[str, Any]:
    return {
        "id": t.id,
        "number": t.number,
        "subject": t.subject,
        "status": t.status,
        "priority": t.priority,
        "component": t.component,
        "product_version": t.product_version,
        "created_at": t.created_at.isoformat(),
        "first_response_due_at": t.first_response_due_at.isoformat() if t.first_response_due_at else None,
        "data_class": t.data_class,
    }


def _visible(t: Ticket, p: Principal) -> bool:
    return not t.restricted or p.is_admin


def build() -> MCPServer:
    s = get_settings()
    server = MCPServer(
        name="relayops",
        title="RelayOps (read-only)",
        instructions="Read-only access to one RelayOps organization's tickets, investigations, knowledge, and "
        "approved artifacts. Nothing can be changed through this server.",
        version="0.2.0",
        token_verifier=RelayTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(s.api_origin),
            resource_server_url=AnyHttpUrl(_resource_url()),
            required_scopes=[SCOPE],
            validate_token_resource=False,
        ),
    )

    @server.tool(annotations=READ_ONLY)
    async def search_knowledge(query: str, k: int = 5) -> dict[str, Any]:
        """Search current staff-visible knowledge (articles, policies, runbooks, release notes) by keyword."""
        k = max(1, min(k, 10))

        def go(db: Any, p: Principal) -> dict[str, Any]:
            res = retrieval.search(db, retrieval.RetrievalScope.for_principal(p), query[:300], mode="lexical", k=k)
            return {
                "results": [
                    {
                        "title": h["title"],
                        "slug": h["slug"],
                        "kind": h["kind"],
                        "visibility": h["visibility"],
                        "excerpt": h["text"][:400],
                    }
                    for h in res["results"]
                ]
            }

        return await _call(go)

    @server.tool(annotations=READ_ONLY)
    async def list_open_tickets(limit: int = 20) -> dict[str, Any]:
        """Open tickets, soonest first-response deadline first."""
        limit = max(1, min(limit, 50))

        def go(db: Any, p: Principal) -> dict[str, Any]:
            rows, total = ticket_service.list_tickets(db, p, status="open", sort="due", page_size=limit)
            return {"total": total, "tickets": [_ticket_out(t) for t in rows if _visible(t, p)]}

        return await _call(go)

    @server.tool(annotations=READ_ONLY)
    async def get_ticket(ticket_id: str) -> dict[str, Any]:
        """One ticket's status and target, plus its latest investigation's route and review state."""

        def go(db: Any, p: Principal) -> dict[str, Any]:
            t = scoped.get_ticket(db, p, ticket_id)
            if not _visible(t, p):
                raise AccessDenied("restricted security tickets are visible to admin tokens only")
            run = (
                db.execute(
                    scoped.runs(p)
                    .where(InvestigationRun.ticket_id == t.id)
                    .order_by(InvestigationRun.created_at.desc())
                )
                .scalars()
                .first()
            )
            return {**_ticket_out(t), "latest_investigation": _run_out(db, run) if run else None}

        return await _call(go)

    @server.tool(annotations=READ_ONLY)
    async def get_investigation(run_id: str) -> dict[str, Any]:
        """An investigation's status, route, verification result, and review decision (no raw model output)."""

        def go(db: Any, p: Principal) -> dict[str, Any]:
            run = scoped.get_run(db, p, run_id)
            t = db.get(Ticket, run.ticket_id)
            if t is not None and not _visible(t, p):
                raise AccessDenied("restricted security tickets are visible to admin tokens only")
            return _run_out(db, run)

        return await _call(go)

    @server.tool(annotations=READ_ONLY)
    async def list_approved_artifacts(kind: str | None = None) -> dict[str, Any]:
        """Current versions of saved artifacts (handoffs, summaries) in this organization."""

        def go(db: Any, p: Principal) -> dict[str, Any]:
            return {
                "artifacts": [
                    {
                        "id": a.id,
                        "kind": a.kind,
                        "title": a.title,
                        "version": v.version,
                        "created_at": v.created_at.isoformat(),
                    }
                    for a, v in artifacts.list_artifacts(db, p, kind=kind)
                ][:50]
            }

        return await _call(go)

    return server


def _run_out(db: Any, run: InvestigationRun) -> dict[str, Any]:
    prop = (
        db.execute(select(Proposal).where(Proposal.run_id == run.id).order_by(Proposal.version.desc()))
        .scalars()
        .first()
    )
    return {
        "id": run.id,
        "status": run.status,
        "route": run.route,
        "created_at": run.created_at.isoformat(),
        "proposal": None
        if prop is None
        else {
            "version": prop.version,
            "status": prop.status,
            "verification": prop.verification_status,
            "action_kind": prop.action_kind,
        },
    }


def http_app() -> Any:
    """Stateless JSON streamable HTTP. Host and Origin checks guard against DNS rebinding."""
    s = get_settings()
    api_host = urlparse(s.api_origin).netloc
    security = TransportSecuritySettings(
        allowed_hosts=sorted({api_host, "127.0.0.1:*", "localhost:*", "[::1]:*"}),
        allowed_origins=sorted({s.api_origin, s.web_origin, "http://127.0.0.1:*", "http://localhost:*"}),
    )
    return server.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True, transport_security=security
    )


class Mounted:
    """ASGI app mounted at /mcp. The SDK's session manager runs once per instance, so each API lifespan builds
    a fresh streamable HTTP app and runs its manager for the life of the process."""

    def __init__(self) -> None:
        self.app: Any = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        self.app = http_app()
        async with server.session_manager.run():
            try:
                yield
            finally:
                self.app = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self.app is None:
            if scope["type"] == "http":
                await send(
                    {"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"text/plain")]}
                )
                await send({"type": "http.response.body", "body": b"MCP endpoint is not running"})
            return
        await self.app(scope, receive, send)


server = build()
mounted = Mounted()
