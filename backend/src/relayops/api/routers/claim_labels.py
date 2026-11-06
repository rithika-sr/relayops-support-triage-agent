"""Human claim labels: record, list, export, import, and agreement statistics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from relayops.api.deps import DB, admin_principal, staff_principal
from relayops.domain.scope import Principal
from relayops.services import claim_labels

router = APIRouter(tags=["annotations"])


class AnnotateBody(BaseModel):
    verdict: str
    claim_sha256: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class ImportBody(BaseModel):
    annotator_label: str = Field(min_length=1, max_length=80)
    items: list[dict[str, Any]]
    dry_run: bool = True


@router.post("/proposals/{proposal_id}/claims/{index}/annotations", status_code=201)
def annotate(
    proposal_id: str, index: int, body: AnnotateBody, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    row = claim_labels.annotate(
        db, p, proposal_id, index, verdict=body.verdict, note=body.note, expected_sha=body.claim_sha256
    )
    return {"id": row.id, "claim_index": row.claim_index, "verdict": row.verdict}


@router.get("/proposals/{proposal_id}/annotations")
def list_for_proposal(
    proposal_id: str, p: Principal = Depends(staff_principal), db: Session = DB
) -> list[dict[str, Any]]:
    return claim_labels.for_proposal(db, p, proposal_id)


@router.get("/annotations/export")
def export(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return {"format": "relayops.claim_annotations.v1", "items": claim_labels.export(db, p)}


@router.post("/annotations/import")
def import_labels(body: ImportBody, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    return claim_labels.import_labels(db, p, body.items, annotator_label=body.annotator_label, dry_run=body.dry_run)


@router.get("/annotations/stats")
def stats(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return claim_labels.stats(db, p)
