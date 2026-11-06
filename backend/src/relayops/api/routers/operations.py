"""Artifacts and audit history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from relayops.api.deps import DB, admin_principal, staff_principal
from relayops.api.serializers import iso
from relayops.domain.scope import Principal
from relayops.services import artifacts, audit

router = APIRouter(tags=["operations"])


class ArtifactEdit(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    note: str | None = Field(default=None, max_length=500)


def _artifact(a: Any, v: Any) -> dict[str, Any]:
    return {
        "id": a.id,
        "kind": a.kind,
        "title": a.title,
        "ticket_id": a.ticket_id,
        "run_id": a.run_id,
        "incident_id": a.incident_id,
        "review_status": a.review_status,
        "current_version": a.current_version,
        "verification_status": v.verification_status,
        "content_hash": v.content_hash,
        "created_at": iso(a.created_at),
        "updated_at": iso(v.created_at),
    }


@router.get("/artifacts")
def list_artifacts(
    kind: str | None = None, p: Principal = Depends(staff_principal), db: Session = DB
) -> list[dict[str, Any]]:
    return [_artifact(a, v) for a, v in artifacts.list_artifacts(db, p, kind=kind)]


@router.get("/artifacts/{artifact_id}")
def artifact_detail(artifact_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    a, versions = artifacts.detail(db, p, artifact_id)
    return {
        "artifact": _artifact(a, versions[0]),
        "versions": [
            {
                "version": v.version,
                "content": v.content,
                "content_hash": v.content_hash,
                "sources": v.sources,
                "verification": v.verification,
                "verification_status": v.verification_status,
                "verified_content_hash": v.verified_content_hash,
                "created_by": v.created_by,
                "note": v.note,
                "created_at": iso(v.created_at),
            }
            for v in versions
        ],
    }


@router.post("/artifacts/{artifact_id}/versions", status_code=201)
def edit_artifact(
    artifact_id: str, body: ArtifactEdit, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    v = artifacts.edit(db, p, artifact_id, content=body.content, note=body.note)
    return {"version": v.version, "verification_status": v.verification_status}


@router.post("/artifacts/{artifact_id}/revalidate")
def revalidate(artifact_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    v = artifacts.revalidate(db, p, artifact_id)
    return {"version": v.version, "verification_status": v.verification_status, "verification": v.verification}


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(
    artifact_id: str, format: str = "md", p: Principal = Depends(staff_principal), db: Session = DB
) -> Response:
    body, media, name = artifacts.export(db, p, artifact_id, format)
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/audit")
def audit_log(
    action: str | None = None,
    outcome: str | None = None,
    page: int = 1,
    p: Principal = Depends(admin_principal),
    db: Session = DB,
) -> dict[str, Any]:
    rows = audit.list_events(db, p, action=action, outcome=outcome, limit=100, offset=(max(page, 1) - 1) * 100)
    return {
        "items": [
            {
                "id": e.id,
                "action": e.action,
                "actor_kind": e.actor_kind,
                "actor_user_id": e.actor_user_id,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "outcome": e.outcome,
                "detail": e.detail,
                "created_at": iso(e.created_at),
            }
            for e in rows
        ],
        "page": page,
    }
