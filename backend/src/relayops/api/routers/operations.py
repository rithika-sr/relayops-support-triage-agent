"""Engineering board, incidents, artifacts, playbooks, timeline, audit, and evaluations."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from relayops.api.deps import DB, admin_principal, current_principal, staff_principal
from relayops.api.serializers import iso
from relayops.domain.scope import Principal
from relayops.services import artifacts, audit, engineering, evaluations, incidents, playbooks, timeline

router = APIRouter(tags=["operations"])


class ConfirmBody(BaseModel):
    title: str = Field(default="", max_length=300)
    severity: str = "P3"
    window_hours: int = 6
    incident_id: str | None = None
    expected_ticket_ids: list[str]


class IncidentPatch(BaseModel):
    status: str | None = None
    public_summary: str | None = Field(default=None, max_length=2000)
    public_visible: bool | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)


class ArtifactEdit(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    note: str | None = Field(default=None, max_length=500)


class PlaybookSave(BaseModel):
    config: dict[str, Any]


@router.get("/engineering/board")
def board(
    component: str | None = None, kind: str | None = None, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    return engineering.board(db, p, component=component, kind=kind)


@router.get("/engineering/issues/{issue_id}")
def issue(issue_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return engineering.issue_detail(db, p, issue_id)


@router.get("/incidents")
def list_incidents(p: Principal = Depends(current_principal), db: Session = DB) -> list[dict[str, Any]]:
    return incidents.list_incidents(db, p)


@router.get("/incidents/candidates")
def candidates(
    window_hours: int = 6, p: Principal = Depends(staff_principal), db: Session = DB
) -> list[dict[str, Any]]:
    return incidents.candidates(db, p, window_hours=window_hours)


@router.post("/incidents/candidates/{key}/confirm", status_code=201)
def confirm(key: str, body: ConfirmBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    inc = incidents.confirm_candidate(
        db,
        p,
        key,
        title=body.title,
        severity=body.severity,
        window_hours=body.window_hours,
        incident_id=body.incident_id,
        expected_ticket_ids=body.expected_ticket_ids,
    )
    return incidents.detail(db, p, inc.id)


@router.get("/incidents/export.csv")
def export_incidents(p: Principal = Depends(staff_principal), db: Session = DB) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "title",
            "component",
            "status",
            "severity",
            "started_at",
            "resolved_at",
            "linked_tickets",
            "affected_accounts",
            "public_visible",
        ]
    )
    for i in incidents.list_incidents(db, p):
        w.writerow(
            [
                i["id"],
                i["title"],
                i["component"],
                i["status"],
                i["severity"],
                i["started_at"],
                i["resolved_at"] or "",
                i["linked_tickets"],
                i["affected_accounts"],
                i["public_visible"],
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="relayops-incidents.csv"'},
    )


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    return incidents.detail(db, p, incident_id)


@router.patch("/incidents/{incident_id}")
def patch_incident(
    incident_id: str, body: IncidentPatch, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    incidents.update_incident(db, p, incident_id, body.model_dump(exclude_unset=True))
    return incidents.detail(db, p, incident_id)


@router.post("/incidents/{incident_id}/summary", status_code=201)
def incident_summary(incident_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    art, v = incidents.draft_summary(db, p, incident_id)
    return {"artifact_id": art.id, "version": v.version}


@router.get("/tickets/{ticket_id}/timeline")
def ticket_timeline(ticket_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return timeline.ticket_timeline(db, p, ticket_id)


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


@router.get("/playbooks")
def list_playbooks(p: Principal = Depends(staff_principal), db: Session = DB) -> list[dict[str, Any]]:
    return playbooks.list_playbooks(db, p)


@router.get("/playbooks/{key}")
def playbook_detail(key: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return playbooks.detail(db, p, key)


@router.post("/playbooks/{key}/revisions", status_code=201)
def save_playbook(
    key: str, body: PlaybookSave, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    return playbooks.save_revision(db, p, key, body.config)


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


@router.post("/evaluations/import")
def import_evals(p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    return evaluations.import_reports(db, p)


@router.get("/evaluations")
def list_evals(p: Principal = Depends(admin_principal), db: Session = DB) -> list[dict[str, Any]]:
    return evaluations.list_reports(db, p)


@router.get("/evaluations/{report_id}")
def eval_detail(report_id: str, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    return evaluations.report_detail(db, p, report_id)
