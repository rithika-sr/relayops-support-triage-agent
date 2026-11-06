"""Outbound GitHub Issues connector for approved engineering handoffs.

Shape: GitHub REST v3 (`POST /repos/{owner}/{repo}/issues`, `GET /repos/{owner}/{repo}/issues`). In this
release the connector only talks to loopback hosts, which is where the local GitHub-shaped test service
runs. Writing to github.com or any other remote host is a live external operation; it stays refused until
a separately authorized live operation enables it. A token alone does not authorize it.

Delivery runs from the outbox after the local action commits. Each issue body carries a hidden marker with
the action's idempotency key. An ambiguous outcome (timeout, 5xx, lost response) is recorded as `unknown`
and resolved by searching for the marker, never by creating again blindly.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import ActionRecord, Connection, OutboxMessage
from relayops.repositories import scoped
from relayops.services import audit
from relayops.services.actions import RemoteRejected, RemoteTimeout
from relayops.services.ingestion import decrypt_secret, encrypt_secret, get_connection, require_unique_name

TOPIC = "github.create_issue"
REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
LABEL = "relayops"
MAX_ATTEMPTS = 5
LIVE_REFUSAL = (
    "remote GitHub hosts are not enabled: writing to a live tracker needs a separately authorized "
    "live operation. Use a loopback test service."
)


def loopback(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def marker(key: str) -> str:
    return f"<!-- relayops:action:{key} -->"


class GitHubIssuesClient:
    def __init__(
        self,
        base_url: str,
        repo: str,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not loopback(base_url):
            raise ValidationFailed(LIVE_REFUSAL)
        self.repo = repo
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "relayops-connector",
            },
        )

    def check(self) -> dict[str, Any]:
        r = self._send("GET", f"/repos/{self.repo}")
        return {"full_name": r.json().get("full_name"), "permissions": r.json().get("permissions")}

    def create_issue(self, *, marker: str, title: str, body: str = "") -> str:
        r = self._send(
            "POST",
            f"/repos/{self.repo}/issues",
            json={"title": title[:250], "body": f"{body}\n\n{marker}", "labels": [LABEL]},
        )
        return f"{self.repo}#{r.json()['number']}"

    def find_by_marker(self, marker: str) -> str | None:
        for page in range(1, 11):
            r = self._send(
                "GET",
                f"/repos/{self.repo}/issues",
                params={"state": "all", "labels": LABEL, "per_page": 100, "page": page},
            )
            items = r.json()
            for it in items:
                if marker in (it.get("body") or ""):
                    return f"{self.repo}#{it['number']}"
            if len(items) < 100:
                return None
        raise RemoteTimeout("marker search exceeded 1000 issues; operator decision required")

    def _send(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.TimeoutException as exc:
            raise RemoteTimeout(f"{method} {path} timed out") from exc
        except httpx.TransportError as exc:
            raise RemoteTimeout(f"{method} {path} failed: {exc.__class__.__name__}") from exc
        if r.status_code >= 500 or r.status_code == 429:
            raise RemoteTimeout(f"{method} {path} returned {r.status_code}")
        if r.status_code >= 400:
            raise RemoteRejected(f"{method} {path} returned {r.status_code}: {r.text[:200]}")
        return r


# --- connections --------------------------------------------------------------------------------------------


def create_connection(db: Session, p: Principal, *, name: str, base_url: str, repo: str, token: str) -> Connection:
    scoped.require_admin(p)
    if not name.strip():
        raise ValidationFailed("name is required")
    if not REPO.match(repo):
        raise ValidationFailed("repo must look like owner/name")
    if urlparse(base_url).scheme not in ("http", "https"):
        raise ValidationFailed("base URL must be http or https")
    if not loopback(base_url):
        raise ValidationFailed(LIVE_REFUSAL)
    if not token.strip():
        raise ValidationFailed("a token is required")
    require_unique_name(db, p.organization_id, name.strip()[:120])
    c = Connection(
        organization_id=p.organization_id,
        kind="github_issues",
        name=name.strip()[:120],
        status="configured",
        config={"base_url": base_url.rstrip("/"), "repo": repo, "target": "loopback"},
        secret_encrypted=encrypt_secret(token.strip()),
        created_by_user_id=p.user_id,
    )
    db.add(c)
    db.flush()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="connection.created",
        target_type="connection",
        target_id=c.id,
        detail={"kind": c.kind, "repo": repo},
    )
    return c


def client_for(c: Connection, **kw: Any) -> GitHubIssuesClient:
    return GitHubIssuesClient(c.config["base_url"], c.config["repo"], decrypt_secret(c.secret_encrypted), **kw)


def _mark(c: Connection, ok: bool, error: str | None = None) -> None:
    now = utcnow()
    if ok:
        c.status, c.last_success_at = "healthy", now
    else:
        c.status, c.last_error, c.last_error_at = "degraded", (error or "")[:500], now


def test_connection(db: Session, p: Principal, connection_id: str, **kw: Any) -> dict[str, Any]:
    """A real read against the configured service. Status reflects this result, nothing else."""
    scoped.require_admin(p)
    c = get_connection(db, p, connection_id)
    if c.kind != "github_issues":
        raise ValidationFailed("not a GitHub connection")
    try:
        info = client_for(c, **kw).check()
    except (RemoteRejected, RemoteTimeout) as exc:
        _mark(c, False, str(exc))
        return {"ok": False, "status": c.status, "error": str(exc)}
    _mark(c, True)
    return {"ok": True, "status": c.status, "repository": info["full_name"]}


def active_connection(db: Session, organization_id: str) -> Connection | None:
    return (
        db.execute(
            select(Connection)
            .where(
                Connection.organization_id == organization_id,
                Connection.kind == "github_issues",
                Connection.status.in_(("configured", "healthy", "degraded")),
            )
            .order_by(Connection.created_at)
        )
        .scalars()
        .first()
    )


# --- delivery -----------------------------------------------------------------------------------------------


def deliver(db: Session, msg: OutboxMessage, **kw: Any) -> str:
    """Deliver one github.create_issue message; returns the message status."""
    record = db.get(ActionRecord, msg.action_id)
    c = db.get(Connection, msg.payload["connection_id"])
    assert record is not None
    ext = dict(record.receipt.get("external") or {})
    if c is None or c.status == "disconnected":
        msg.status, ext["status"] = "failed", "not_sent"
        ext["error"] = "connection disabled before delivery; nothing was sent"
        record.receipt = {**record.receipt, "external": ext}
        return msg.status
    msg.attempts += 1
    key = marker(record.idempotency_key)
    try:
        gh = client_for(c, **kw)
        found = gh.find_by_marker(key) if ext.get("status") == "unknown" else None
        remote = found or gh.create_issue(marker=key, title=msg.payload["title"], body=msg.payload["body"])
    except RemoteRejected as exc:
        msg.status, ext = "failed", {**ext, "status": "rejected", "error": str(exc)}
        _mark(c, False, str(exc))
    except RemoteTimeout as exc:
        ext = {**ext, "status": "unknown", "error": str(exc), "needs_reconciliation": True}
        msg.status = "failed" if msg.attempts >= MAX_ATTEMPTS else "pending"
        if msg.status == "pending":  # back off: 30s, 60s, 120s, ...
            retry_at = utcnow() + timedelta(seconds=30 * 2 ** (msg.attempts - 1))
            msg.payload = {**msg.payload, "next_attempt_at": retry_at.isoformat()}
        if msg.status == "failed":
            ext["error"] = f"{exc}; still unknown after {msg.attempts} attempts; operator decision required"
        _mark(c, False, str(exc))
    else:
        ext = {"status": "reconciled" if found else "created", "issue": remote, "needs_reconciliation": False}
        msg.status, msg.delivered_at = "delivered", utcnow()
        _mark(c, True)
    record.receipt = {
        **record.receipt,
        "external": {**ext, "adapter": "github_issues", "repo": c.config["repo"], "attempts": msg.attempts},
    }
    audit.record(
        db,
        organization_id=record.organization_id,
        action="action.external_push",
        target_type="action",
        target_id=record.id,
        actor_kind="system",
        outcome={"delivered": "ok", "pending": "unknown"}.get(msg.status, "failed"),
        detail={"adapter": "github_issues", "external_status": ext["status"]},
    )
    return msg.status
