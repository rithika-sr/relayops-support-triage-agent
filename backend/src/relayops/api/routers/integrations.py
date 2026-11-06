"""Imports, connections, and the signed inbound webhook."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.api.deps import DB, admin_principal, staff_principal
from relayops.api.serializers import iso
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import Connection, ImportBatch
from relayops.services import github_connector, ingestion

router = APIRouter(tags=["integrations"])


class WebhookConnectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_map: dict[str, str]


def _fmt(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".json"):
        return "json"
    raise ValidationFailed("upload a .csv or .json file")


@router.post("/imports/preview")
async def preview_import(
    file: UploadFile = File(...), p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    raw = await file.read(ingestion.MAX_IMPORT_BYTES + 1)
    return ingestion.plan_import(db, p, fmt=_fmt(file.filename or ""), raw=raw)


@router.post("/imports", status_code=201)
async def commit_import(
    file: UploadFile = File(...),
    expected_sha256: str = Form(...),
    p: Principal = Depends(staff_principal),
    db: Session = DB,
) -> dict[str, Any]:
    raw = await file.read(ingestion.MAX_IMPORT_BYTES + 1)
    b = ingestion.commit_import(
        db,
        p,
        fmt=_fmt(file.filename or ""),
        raw=raw,
        filename=file.filename or "import",
        expected_sha256=expected_sha256,
    )
    return _batch(b)


def _batch(b: ImportBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "filename": b.filename,
        "status": b.status,
        "total_rows": b.total_rows,
        "created_count": b.created_count,
        "duplicate_count": b.duplicate_count,
        "error_count": b.error_count,
        "errors": b.errors,
        "content_sha256": b.content_sha256,
        "created_at": iso(b.created_at),
    }


@router.get("/imports")
def list_imports(p: Principal = Depends(staff_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ImportBatch)
        .where(ImportBatch.organization_id == p.organization_id)
        .order_by(ImportBatch.created_at.desc())
        .limit(50)
    ).scalars()
    return [_batch(b) for b in rows]


@router.get("/integrations")
def list_connections(p: Principal = Depends(admin_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Connection).where(Connection.organization_id == p.organization_id).order_by(Connection.created_at)
    ).scalars()
    return [ingestion.connection_dict(c) for c in rows]


@router.post("/integrations/webhooks", status_code=201)
def create_webhook(
    body: WebhookConnectionBody, request: Request, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    c, secret = ingestion.create_webhook_connection(db, p, name=body.name, account_map=body.account_map)
    base = str(request.base_url).rstrip("/")
    return {
        "connection": ingestion.connection_dict(c),
        "signing_secret": secret,
        "endpoint": f"{base}/api/ingest/webhooks/{c.id}",
        "note": "The signing secret is shown once. Sign `<timestamp>.<raw body>` with HMAC-SHA256.",
    }


@router.post("/integrations/{connection_id}/rotate-secret")
def rotate(connection_id: str, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, str]:
    return {"signing_secret": ingestion.rotate_secret(db, p, connection_id)}


class GitHubConnectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=300)
    repo: str = Field(min_length=3, max_length=201)
    token: str = Field(min_length=1, max_length=500)


@router.post("/integrations/github", status_code=201)
def create_github(
    body: GitHubConnectionBody, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    c = github_connector.create_connection(
        db, p, name=body.name, base_url=body.base_url, repo=body.repo, token=body.token
    )
    return {
        "connection": ingestion.connection_dict(c),
        "note": "Token stored encrypted. Use Test connection to check it; status reflects that result.",
    }


@router.post("/integrations/{connection_id}/test")
def test_github(connection_id: str, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    return github_connector.test_connection(db, p, connection_id)


@router.post("/integrations/{connection_id}/{action}")
def toggle(
    connection_id: str, action: str, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    if action not in ("enable", "disable"):
        raise ValidationFailed("action must be enable or disable")
    return ingestion.connection_dict(ingestion.set_enabled(db, p, connection_id, action == "enable"))


@router.get("/integrations/{connection_id}/receipts")
def list_receipts(
    connection_id: str, p: Principal = Depends(admin_principal), db: Session = DB
) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "external_event_id": r.external_event_id,
            "status": r.status,
            "reason": r.reason,
            "ticket_id": r.ticket_id,
            "received_at": iso(r.received_at),
            "source_event_at": iso(r.source_event_at),
        }
        for r in ingestion.receipts(db, p, connection_id)
    ]


@router.post("/ingest/webhooks/{connection_id}")
async def inbound_webhook(connection_id: str, request: Request, db: Session = DB) -> JSONResponse:
    """Authenticated by HMAC signature over the raw body, not by cookies (so CSRF does not apply)."""
    raw = await request.body()
    try:
        r = ingestion.receive_webhook(
            db,
            connection_id,
            raw,
            timestamp=request.headers.get("x-relayops-timestamp"),
            signature=request.headers.get("x-relayops-signature"),
        )
    except ingestion.WebhookRejected as exc:
        db.commit()  # keep the connection's last-error state
        return JSONResponse({"detail": exc.reason}, status_code=exc.status)
    code = 202 if r.status == "accepted" else 422
    return JSONResponse(
        {"receipt_id": r.id, "status": r.status, "reason": r.reason, "ticket_id": r.ticket_id}, status_code=code
    )
