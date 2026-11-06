"""Read-only MCP endpoint: token scope, revocation, organization scope, and no write tools."""

from __future__ import annotations

import socket
import threading
import time

import anyio
import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from relayops.core.db import new_session
from relayops.models import Ticket
from tests.agent_helpers import ADMIN, CUSTOMER, SUPPORT, client, export_ticket, seeded

ACCEPT = "application/json, text/event-stream"


def _token(admin) -> dict:
    r = admin.post("/api/settings/tokens", json={"name": "mcp test", "scopes": ["mcp:read"]})
    assert r.status_code == 201, r.text
    return r.json()


def _rpc(c, token, method, params=None, *, rid=1):
    h = {"Accept": ACCEPT, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return c.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def _call(c, token, name, **args):
    r = _rpc(c, token, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    return r.json()["result"]


@pytest.fixture
def world(db, tmp_path):
    creds = seeded(db, tmp_path)
    admin, cust = client(ADMIN, creds), client(CUSTOMER, creds)
    tid = export_ticket(cust)
    with new_session() as s:
        other = s.execute(select(Ticket.id).where(Ticket.organization_id == "org_quillstack")).scalars().first()
    from relayops.api.main import app

    with TestClient(app, base_url="http://localhost:8020") as c:
        yield {"c": c, "admin": admin, "support": client(SUPPORT, creds), "tid": tid, "other": other}


def test_auth_is_required_and_only_mcp_read_tokens_work(world):
    c = world["c"]
    r = _rpc(c, None, "tools/list")
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
    assert _rpc(c, "rlo_not-a-real-token", "tools/list").status_code == 401
    # A browser session cookie is not an MCP credential.
    sess = world["support"]
    cookie = "; ".join(f"{k}={v}" for k, v in sess.cookies.items())
    r = c.post(
        "/mcp/", headers={"Accept": ACCEPT, "Cookie": cookie}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert r.status_code == 401
    # Only admins mint tokens, and only with the read scope.
    assert sess.post("/api/settings/tokens", json={"name": "x", "scopes": ["mcp:read"]}).status_code == 403
    assert world["admin"].post("/api/settings/tokens", json={"name": "x", "scopes": ["mcp:write"]}).status_code == 422


def test_tools_are_read_only_and_scoped(world):
    c, tok = world["c"], _token(world["admin"])["token"]
    tools = _rpc(c, tok, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "search_knowledge",
        "list_open_tickets",
        "get_ticket",
        "get_investigation",
        "list_approved_artifacts",
    }
    assert all(t["annotations"]["readOnlyHint"] and not t["annotations"]["destructiveHint"] for t in tools)

    mine = _call(c, tok, "get_ticket", ticket_id=world["tid"])
    assert not mine.get("isError") and mine["structuredContent"]["id"] == world["tid"]
    other = _call(c, tok, "get_ticket", ticket_id=world["other"])
    assert other["isError"] and "not found" in other["content"][0]["text"]  # another organization: not visible
    listed = _call(c, tok, "list_open_tickets", limit=5)["structuredContent"]
    assert listed["tickets"] and all(t["id"] != world["other"] for t in listed["tickets"])
    hits = _call(c, tok, "search_knowledge", query="export rows limit")["structuredContent"]["results"]
    assert hits and all("excerpt" in h for h in hits)
    # Unknown tools (e.g. an attempted write) are refused.
    bad = _rpc(c, tok, "tools/call", {"name": "approve_proposal", "arguments": {}}).json()
    assert "error" in bad or bad["result"].get("isError")


def test_revocation_takes_effect_on_the_next_request(world):
    c, admin = world["c"], world["admin"]
    tok = _token(admin)
    assert _rpc(c, tok["token"], "tools/list").status_code == 200
    assert admin.post(f"/api/settings/tokens/{tok['id']}/revoke").status_code == 200
    assert _rpc(c, tok["token"], "tools/list").status_code == 401


def test_rest_api_rejects_mcp_tokens(world):
    from relayops.api.main import app

    tok = _token(world["admin"])["token"]
    bare = TestClient(app)
    assert bare.get("/api/tickets", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_official_sdk_client_over_a_real_socket(world):
    """The SDK's own client talks to the endpoint served by uvicorn."""
    from relayops.api.main import app

    tok = _token(world["admin"])["token"]
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    async def go() -> tuple[set[str], dict]:
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {tok}"}, timeout=20) as http:
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp/", http_client=http) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    res = await session.call_tool("get_ticket", {"ticket_id": world["tid"]})
                    return {x.name for x in listed.tools}, res.structured_content or {}

    try:
        names, ticket = anyio.run(go)
    finally:
        server.should_exit = True
        t.join(timeout=10)
    assert "get_ticket" in names and ticket["id"] == world["tid"]
