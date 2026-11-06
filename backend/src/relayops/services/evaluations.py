"""Evaluation report ingestion. Reports are produced by evals/runners and loaded as-is with provenance."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.core.config import REPO_ROOT
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import EvalReport
from relayops.repositories import scoped
from relayops.services import audit

RESULTS = REPO_ROOT / "evals" / "results"
REQUIRED = ("report_key", "profile", "metadata", "summary", "cases")


def import_reports(db: Session, p: Principal) -> dict[str, Any]:
    scoped.require_admin(p)
    loaded, skipped = [], []
    for path in sorted(RESULTS.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            skipped.append({"file": path.name, "reason": "invalid JSON"})
            continue
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            skipped.append({"file": path.name, "reason": f"missing {missing}"})
            continue
        row = db.execute(
            select(EvalReport).where(
                EvalReport.organization_id == p.organization_id, EvalReport.report_key == data["report_key"]
            )
        ).scalar_one_or_none()
        if row is None:
            row = EvalReport(organization_id=p.organization_id, report_key=data["report_key"])
            db.add(row)
        row.profile = data["profile"]
        row.report_metadata = data["metadata"]
        row.summary = data["summary"]
        row.cases = data["cases"]
        row.source_path = str(path.relative_to(REPO_ROOT))
        row.notes = data.get("notes")
        loaded.append(data["report_key"])
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="evaluation.imported",
        target_type="eval_report",
        target_id="*",
        detail={"loaded": loaded, "skipped": skipped},
    )
    return {"loaded": loaded, "skipped": skipped}


def list_reports(db: Session, p: Principal) -> list[dict[str, Any]]:
    scoped.require_admin(p)
    rows = db.execute(
        select(EvalReport).where(EvalReport.organization_id == p.organization_id).order_by(EvalReport.created_at.desc())
    ).scalars()
    return [
        {
            "id": r.id,
            "report_key": r.report_key,
            "profile": r.profile,
            "metadata": r.report_metadata,
            "summary": r.summary,
            "case_count": len(r.cases),
            "source_path": r.source_path,
            "notes": r.notes,
        }
        for r in rows
    ]


def report_detail(db: Session, p: Principal, report_id: str) -> dict[str, Any]:
    scoped.require_admin(p)
    r = db.execute(
        select(EvalReport).where(EvalReport.organization_id == p.organization_id, EvalReport.id == report_id)
    ).scalar_one_or_none()
    if r is None:
        raise scoped.NotFound("report not found")
    if not isinstance(r.cases, list):
        raise ValidationFailed("report has no case list")
    return {
        "id": r.id,
        "report_key": r.report_key,
        "profile": r.profile,
        "metadata": r.report_metadata,
        "summary": r.summary,
        "cases": r.cases,
        "source_path": r.source_path,
        "notes": r.notes,
    }
