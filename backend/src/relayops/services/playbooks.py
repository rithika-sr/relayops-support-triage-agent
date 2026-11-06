from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.core.security import content_hash
from relayops.domain.playbooks import GRAPH_NODES, READ_TOOLS, PlaybookConfig
from relayops.domain.routes import Route
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import InvestigationRun, Playbook, PlaybookRevision
from relayops.repositories import scoped
from relayops.services import audit


def graph_preview(cfg: dict[str, Any]) -> dict[str, Any]:
    nodes = [{"id": k, "label": label, "kind": kind} for k, label, kind in GRAPH_NODES]
    edges = [{"from": a[0], "to": b[0]} for a, b in zip(GRAPH_NODES, GRAPH_NODES[1:], strict=False)]
    edges.append({"from": "investigate", "to": "investigate", "label": f"up to {cfg['max_turns']} turns"})
    edges.append({"from": "review", "to": "audit_outcome", "label": "rejected"})
    return {"nodes": nodes, "edges": edges, "tools": cfg["allowed_tools"], "routes": cfg["allowed_routes"]}


def list_playbooks(db: Session, p: Principal) -> list[dict[str, Any]]:
    scoped.require_staff(p)
    out = []
    for pb in db.execute(
        select(Playbook).where(Playbook.organization_id == p.organization_id).order_by(Playbook.key)
    ).scalars():
        rev = db.execute(
            select(PlaybookRevision).where(
                PlaybookRevision.playbook_id == pb.id, PlaybookRevision.revision == pb.current_revision
            )
        ).scalar_one()
        counts = dict(
            db.execute(
                select(InvestigationRun.status, func.count(InvestigationRun.id))
                .where(
                    InvestigationRun.organization_id == p.organization_id,
                    InvestigationRun.playbook_key == pb.key,
                    InvestigationRun.mode == "live",
                )
                .group_by(InvestigationRun.status)
            ).all()
        )  # type: ignore[arg-type]
        out.append(
            {
                "id": pb.id,
                "key": pb.key,
                "name": pb.name,
                "description": pb.description,
                "current_revision": pb.current_revision,
                "config": rev.config,
                "config_hash": rev.config_hash,
                "runs_by_status": counts,
            }
        )
    return out


def detail(db: Session, p: Principal, key: str) -> dict[str, Any]:
    scoped.require_staff(p)
    pb = scoped.one(
        db, select(Playbook).where(Playbook.organization_id == p.organization_id, Playbook.key == key), "playbook"
    )
    revs = list(
        db.execute(
            select(PlaybookRevision)
            .where(PlaybookRevision.playbook_id == pb.id)
            .order_by(PlaybookRevision.revision.desc())
        ).scalars()
    )
    current = next(r for r in revs if r.revision == pb.current_revision)
    runs = db.execute(
        scoped.runs(p)
        .where(InvestigationRun.playbook_key == key)
        .order_by(InvestigationRun.created_at.desc())
        .limit(20)
    ).scalars()
    return {
        "playbook": {
            "id": pb.id,
            "key": pb.key,
            "name": pb.name,
            "description": pb.description,
            "current_revision": pb.current_revision,
        },
        "config": current.config,
        "graph": graph_preview(current.config),
        "revisions": [
            {
                "revision": r.revision,
                "config": r.config,
                "config_hash": r.config_hash,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat(),
            }
            for r in revs
        ],
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "route": r.route,
                "playbook_revision": r.playbook_revision,
                "created_at": r.created_at.isoformat(),
                "mode": r.mode,
            }
            for r in runs
        ],
        "options": {"tools": list(READ_TOOLS), "routes": [r.value for r in Route]},
    }


def save_revision(db: Session, p: Principal, key: str, config: dict[str, Any]) -> dict[str, Any]:
    scoped.require_admin(p)
    pb = scoped.one(
        db,
        select(Playbook).where(Playbook.organization_id == p.organization_id, Playbook.key == key).with_for_update(),
        "playbook",
    )
    try:
        cfg = PlaybookConfig.model_validate(config).model_dump(mode="json")
    except ValidationError as exc:
        raise ValidationFailed("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc
    current = db.execute(
        select(PlaybookRevision).where(
            PlaybookRevision.playbook_id == pb.id, PlaybookRevision.revision == pb.current_revision
        )
    ).scalar_one()
    if current.config_hash == content_hash(cfg):
        raise ValidationFailed("no changes to save")
    pb.current_revision += 1
    db.add(
        PlaybookRevision(
            playbook_id=pb.id,
            organization_id=p.organization_id,
            revision=pb.current_revision,
            config=cfg,
            config_hash=content_hash(cfg),
            created_by=p.user_id,
        )
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="playbook.revised",
        target_type="playbook",
        target_id=pb.id,
        detail={"key": key, "revision": pb.current_revision},
    )
    db.flush()
    return detail(db, p, key)
