"""Ticket ingestion beyond the portal: validated CSV/JSON imports and signed inbound webhooks.

Scope always comes from server-side configuration: an import runs as the authenticated staff member's
organization, and a webhook connection maps external account references to customer accounts in its config.
Request bodies can never name an organization or customer account ID.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.core.config import get_settings
from relayops.domain.scope import Conflict, NotFound, Principal, ValidationFailed
from relayops.models import Connection, CustomerAccount, ImportBatch, IngestionReceipt, Ticket
from relayops.repositories import scoped
from relayops.services import audit, tickets

MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ROWS = 1_000
MAX_WEBHOOK_BYTES = 64_000
SIGNATURE_TOLERANCE = timedelta(minutes=5)
CONNECTION_KINDS = ("inbound_webhook", "github_issues")


# --- secrets ------------------------------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = hashlib.sha256(b"relayops-connection-secrets:" + get_settings().session_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt_secret(token: bytes | None) -> str:
    if not token:
        raise ValidationFailed("connection has no secret configured")
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as exc:  # session secret rotated without re-entering connection secrets
        raise ValidationFailed("connection secret cannot be decrypted; re-enter or rotate it") from exc


# --- rows ---------------------------------------------------------------------------------------------------


class IncomingTicket(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=100)
    account: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=5, max_length=10_000)
    severity: str = "normal"
    component: str | None = None
    product_version: str | None = Field(default=None, max_length=32)
    error_code: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None


def _rows(fmt: str, raw: bytes) -> list[dict[str, Any]]:
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationFailed("import file exceeds 1 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("import file must be UTF-8") from exc
    if fmt == "csv":
        rows = [
            {k.strip(): (v or "").strip() or None for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text))
        ]
    elif fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationFailed(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValidationFailed("JSON import must be a list of objects")
        rows = data
    else:
        raise ValidationFailed("format must be csv or json")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationFailed(f"import has more than {MAX_IMPORT_ROWS} rows")
    if not rows:
        raise ValidationFailed("import has no rows")
    return rows


def _account_lookup(db: Session, p: Principal) -> dict[str, CustomerAccount]:
    out: dict[str, CustomerAccount] = {}
    for a in db.execute(scoped.accounts(p)).scalars():
        out[a.id] = a
        out[a.name.lower()] = a
    return out


def plan_import(db: Session, p: Principal, *, fmt: str, raw: bytes) -> dict[str, Any]:
    """Validate every row and report what a commit would do. Writes nothing."""
    scoped.require_staff(p)
    rows = _rows(fmt, raw)
    accounts = _account_lookup(db, p)
    seen: set[str] = set()
    preview = []
    for i, row in enumerate(rows, start=1):
        entry: dict[str, Any] = {"row": i, "external_id": row.get("external_id"), "status": "ok", "errors": []}
        try:
            item = IncomingTicket.model_validate(row)
        except ValidationError as exc:
            entry["status"] = "error"
            entry["errors"] = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]]
            preview.append(entry)
            continue
        acct = accounts.get(item.account) or accounts.get(item.account.lower())
        if acct is None:
            entry["status"], entry["errors"] = "error", [f"unknown customer account '{item.account}'"]
        elif item.severity not in tickets.SEVERITIES:
            entry["status"], entry["errors"] = "error", [f"unknown severity '{item.severity}'"]
        elif item.external_id in seen:
            entry["status"], entry["errors"] = "duplicate", ["repeated within this file"]
        elif db.execute(
            select(Ticket.id).where(
                Ticket.organization_id == p.organization_id, Ticket.external_event_id == f"import:{item.external_id}"
            )
        ).first():
            entry["status"], entry["errors"] = "duplicate", ["already imported"]
        else:
            entry |= {"account": acct.name, "subject": item.subject}
        seen.add(item.external_id)
        preview.append(entry)
    counts = {s: sum(1 for r in preview if r["status"] == s) for s in ("ok", "duplicate", "error")}
    return {"rows": preview, "counts": counts, "content_sha256": hashlib.sha256(raw).hexdigest()}


def commit_import(
    db: Session, p: Principal, *, fmt: str, raw: bytes, filename: str, expected_sha256: str
) -> ImportBatch:
    """Create tickets for the rows that validated. The file must be the one the user previewed."""
    plan = plan_import(db, p, fmt=fmt, raw=raw)
    if plan["content_sha256"] != expected_sha256:
        raise ValidationFailed("file changed since the preview; preview it again")
    rows = _rows(fmt, raw)
    accounts = _account_lookup(db, p)
    batch = ImportBatch(
        organization_id=p.organization_id,
        actor_user_id=p.user_id,
        filename=filename[:255],
        content_sha256=plan["content_sha256"],
        format=fmt,
        status="committed",
        total_rows=len(rows),
    )
    db.add(batch)
    db.flush()
    for entry, row in zip(plan["rows"], rows, strict=True):
        if entry["status"] != "ok":
            continue
        item = IncomingTicket.model_validate(row)
        acct = accounts.get(item.account) or accounts[item.account.lower()]
        tickets.create_ticket(
            db,
            p,
            tickets.TicketInput(
                subject=item.subject,
                body=item.body,
                reported_severity=item.severity,
                component=item.component,
                product_version=item.product_version,
                error_code=item.error_code,
                customer_account_id=acct.id,
                external_event_id=f"import:{item.external_id}",
                source_kind="import",
                source_system=f"file:{filename[:80]}",
                import_batch_id=batch.id,
                source_event_at=item.occurred_at,
            ),
        )
        batch.created_count += 1
    batch.duplicate_count = plan["counts"]["duplicate"]
    batch.error_count = plan["counts"]["error"]
    batch.errors = [r for r in plan["rows"] if r["status"] != "ok"]
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="import.committed",
        target_type="import_batch",
        target_id=batch.id,
        detail={
            "created": batch.created_count,
            "duplicates": batch.duplicate_count,
            "errors": batch.error_count,
            "sha256": batch.content_sha256,
        },
    )
    return batch


# --- connections --------------------------------------------------------------------------------------------


def connection_dict(c: Connection) -> dict[str, Any]:
    cfg = dict(c.config)
    if c.kind == "github_issues":
        cfg.pop("token", None)
    return {
        "id": c.id,
        "kind": c.kind,
        "name": c.name,
        "status": c.status,
        "config": cfg,
        "has_secret": c.secret_encrypted is not None,
        "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
        "last_error": c.last_error,
        "last_error_at": c.last_error_at.isoformat() if c.last_error_at else None,
        "created_at": c.created_at.isoformat(),
    }


def create_webhook_connection(
    db: Session, p: Principal, *, name: str, account_map: dict[str, str]
) -> tuple[Connection, str]:
    scoped.require_admin(p)
    if not name.strip():
        raise ValidationFailed("name is required")
    if not account_map:
        raise ValidationFailed("map at least one external account reference to a customer account")
    for ref, acct_id in account_map.items():
        if not ref.strip() or len(ref) > 120:
            raise ValidationFailed("external account references must be 1-120 characters")
        scoped.get_account(db, p, acct_id)  # 404 for accounts outside this organization
    require_unique_name(db, p.organization_id, name.strip()[:120])
    secret = "whsec_" + secrets.token_urlsafe(32)
    c = Connection(
        organization_id=p.organization_id,
        kind="inbound_webhook",
        name=name.strip()[:120],
        status="configured",
        config={"account_map": account_map},
        secret_encrypted=encrypt_secret(secret),
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
        detail={"kind": c.kind, "accounts": sorted(account_map.values())},
    )
    return c, secret


def rotate_secret(db: Session, p: Principal, connection_id: str) -> str:
    scoped.require_admin(p)
    c = get_connection(db, p, connection_id)
    if c.kind != "inbound_webhook":
        raise ValidationFailed("only inbound webhook secrets are generated here")
    secret = "whsec_" + secrets.token_urlsafe(32)
    c.secret_encrypted = encrypt_secret(secret)
    c.updated_at = utcnow()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="connection.secret_rotated",
        target_type="connection",
        target_id=c.id,
    )
    return secret


def set_enabled(db: Session, p: Principal, connection_id: str, enabled: bool) -> Connection:
    scoped.require_admin(p)
    c = get_connection(db, p, connection_id)
    c.status = "configured" if enabled else "disconnected"
    c.updated_at = utcnow()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="connection.enabled" if enabled else "connection.disabled",
        target_type="connection",
        target_id=c.id,
    )
    return c


def require_unique_name(db: Session, organization_id: str, name: str) -> None:
    taken = db.execute(
        select(Connection.id).where(Connection.organization_id == organization_id, Connection.name == name)
    ).first()
    if taken:
        raise Conflict(f"a connection named {name!r} already exists")


def get_connection(db: Session, p: Principal, connection_id: str) -> Connection:
    c = db.execute(
        select(Connection).where(Connection.id == connection_id, Connection.organization_id == p.organization_id)
    ).scalar_one_or_none()
    if c is None:
        raise NotFound("connection not found")
    return c


def sign(secret: str, timestamp: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()


class WebhookRejected(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _fail(db: Session, c: Connection, reason: str) -> None:
    c.last_error, c.last_error_at = reason, utcnow()
    if c.status == "healthy":
        c.status = "degraded"


def receive_webhook(
    db: Session, connection_id: str, raw: bytes, *, timestamp: str | None, signature: str | None
) -> IngestionReceipt:
    """Verify, deduplicate, and ingest one signed event. Raises WebhookRejected for unauthenticated input."""
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise WebhookRejected(413, "payload too large")
    c = db.get(Connection, connection_id)
    if c is None or c.kind != "inbound_webhook":
        raise WebhookRejected(404, "unknown connection")
    if c.status == "disconnected":
        raise WebhookRejected(403, "connection is disabled")
    if not timestamp or not signature:
        _fail(db, c, "missing signature headers")
        raise WebhookRejected(401, "missing signature headers")
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=utcnow().tzinfo)
    except (ValueError, OverflowError) as exc:
        _fail(db, c, "bad timestamp")
        raise WebhookRejected(401, "bad timestamp") from exc
    if abs(utcnow() - sent_at) > SIGNATURE_TOLERANCE:
        _fail(db, c, "timestamp outside tolerance (possible replay)")
        raise WebhookRejected(401, "timestamp outside tolerance")
    expected = sign(decrypt_secret(c.secret_encrypted), timestamp, raw)
    if not hmac.compare_digest(expected, signature):
        _fail(db, c, "signature mismatch")
        raise WebhookRejected(401, "signature mismatch")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
        event_id = str(payload.get("event_id", ""))[:160] if isinstance(payload, dict) else ""
    except json.JSONDecodeError:
        payload, event_id = None, ""
    if not event_id:
        _fail(db, c, "payload missing event_id")
        raise WebhookRejected(422, "payload must be a JSON object with event_id")
    prior = db.execute(
        select(IngestionReceipt).where(
            IngestionReceipt.connection_id == c.id, IngestionReceipt.external_event_id == event_id
        )
    ).scalar_one_or_none()
    if prior is not None:
        if prior.payload_sha256 != digest:
            raise WebhookRejected(409, "event_id already received with a different payload")
        return prior  # replay of the same event: idempotent, no new ticket
    receipt = IngestionReceipt(
        organization_id=c.organization_id,
        connection_id=c.id,
        external_event_id=event_id,
        payload_sha256=digest,
        status="accepted",
    )
    try:
        event = IncomingTicket.model_validate(_event_fields(payload))
    except ValidationError as exc:
        receipt.status, receipt.reason = "rejected", "; ".join(e["msg"] for e in exc.errors()[:3])
        db.add(receipt)
        _fail(db, c, f"invalid event {event_id}: {receipt.reason}")
        return receipt
    account_id = c.config.get("account_map", {}).get(event.account)
    if not account_id:
        receipt.status, receipt.reason = "rejected", f"account reference '{event.account}' is not mapped"
        db.add(receipt)
        _fail(db, c, receipt.reason)
        return receipt
    connector = Principal(
        user_id=c.created_by_user_id or "system",
        email="connector@relayops.local",
        name=f"connector:{c.name}",
        membership_id=c.id,
        organization_id=c.organization_id,
        role="support",
        customer_account_id=None,
        via="connector",
    )
    ticket, _ = tickets.create_ticket(
        db,
        connector,
        tickets.TicketInput(
            subject=event.subject,
            body=event.body,
            reported_severity=event.severity,
            component=event.component,
            product_version=event.product_version,
            error_code=event.error_code,
            customer_account_id=account_id,
            external_event_id=f"{c.id}:{event_id}",
            source_kind="connector",
            source_system=c.name,
            source_connection_id=c.id,
            source_event_at=event.occurred_at,
        ),
    )
    ticket.created_by_user_id = None
    receipt.ticket_id, receipt.source_event_at = ticket.id, event.occurred_at
    db.add(receipt)
    c.status, c.last_success_at = "healthy", utcnow()
    return receipt


def _event_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"subject", "body", "severity", "component", "product_version", "error_code", "occurred_at"}
    extra = set(payload) - allowed - {"event_id", "account_ref"}
    if extra:
        # Unknown fields (including attachments, organization or account IDs) are refused, not ignored.
        raise ValidationError.from_exception_data(
            "IncomingTicket", [{"type": "extra_forbidden", "loc": (k,), "input": payload[k]} for k in sorted(extra)]
        )
    return {
        **{k: payload[k] for k in allowed if k in payload},
        "external_id": payload["event_id"],
        "account": payload.get("account_ref") or "",
    }


def receipts(db: Session, p: Principal, connection_id: str, limit: int = 50) -> list[IngestionReceipt]:
    scoped.require_admin(p)
    get_connection(db, p, connection_id)
    return list(
        db.execute(
            select(IngestionReceipt)
            .where(IngestionReceipt.connection_id == connection_id)
            .order_by(IngestionReceipt.received_at.desc())
            .limit(min(limit, 200))
        ).scalars()
    )
