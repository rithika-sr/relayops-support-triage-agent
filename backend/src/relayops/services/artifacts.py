"""Immutable artifact versions with source references, content hashes, and verification state."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.core.security import content_hash
from relayops.domain.scope import Conflict, Principal, ValidationFailed
from relayops.models import Artifact, ArtifactVersion, Incident, IncidentTicketLink, Proposal, Ticket
from relayops.repositories import scoped
from relayops.services import audit


def add_version(
    db: Session,
    artifact: Artifact,
    *,
    content: str,
    sources: list[dict[str, Any]],
    verification: dict[str, Any] | None,
    created_by: str,
    note: str | None = None,
) -> ArtifactVersion:
    digest = content_hash(content)
    latest = db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    version = (latest.version + 1) if latest else 1
    if verification is None:
        status, verified_hash = "unverified", None
    else:
        status, verified_hash = verification["status"], digest
    v = ArtifactVersion(
        artifact_id=artifact.id,
        organization_id=artifact.organization_id,
        version=version,
        content=content,
        content_hash=digest,
        sources=sources,
        verification=verification or {},
        verification_status=status,
        verified_content_hash=verified_hash,
        created_by=created_by,
        note=note,
    )
    db.add(v)
    artifact.current_version = version
    db.flush()
    return v


def for_proposal(db: Session, proposal: Proposal) -> Artifact:
    """One artifact per run proposal chain (customer reply). Edits add versions to the same artifact."""
    root = db.execute(
        select(Artifact).where(Artifact.run_id == proposal.run_id, Artifact.kind == "customer_reply")
    ).scalar_one_or_none()
    if root is None:
        ticket = db.get(Ticket, proposal.ticket_id)
        assert ticket is not None
        root = Artifact(
            data_class=proposal.data_class,
            organization_id=proposal.organization_id,
            customer_account_id=proposal.customer_account_id,
            ticket_id=proposal.ticket_id,
            run_id=proposal.run_id,
            kind="customer_reply",
            title=f"Reply draft for #{ticket.number}: {ticket.subject}"[:300],
        )
        db.add(root)
        db.flush()
    return root


def engineering_brief(db: Session, proposal: Proposal, created_by: str) -> Artifact | None:
    h = proposal.payload.get("handoff")
    if not h:
        return None
    art = db.execute(
        select(Artifact).where(Artifact.run_id == proposal.run_id, Artifact.kind == "engineering_brief")
    ).scalar_one_or_none()
    if art is None:
        art = Artifact(
            data_class=proposal.data_class,
            organization_id=proposal.organization_id,
            customer_account_id=proposal.customer_account_id,
            ticket_id=proposal.ticket_id,
            run_id=proposal.run_id,
            kind="engineering_brief",
            title=f"Engineering brief: {h.get('title') or 'handoff'}"[:300],
        )
        db.add(art)
        db.flush()
    add_version(
        db,
        art,
        content=brief_markdown(h, proposal.payload.get("computed_facts") or {}),
        sources=[e for e in proposal.evidence if e.get("source_type") != "knowledge" or True],
        verification=proposal.verification,
        created_by=created_by,
        note=f"proposal v{proposal.version}",
    )
    return art


def brief_markdown(h: dict[str, Any], facts: dict[str, Any]) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- none recorded"

    return (
        f"# {h.get('title')}\n\nComponent: {h.get('component')}  \nOwner: {h.get('team')}  \n"
        f"Product version: {facts.get('product_version')}  \nError signature: {facts.get('error_signature')}\n\n"
        f"## Summary\n\n{h.get('summary')}\n\n## Observations (from records)\n\n{bullets(h.get('observations', []))}\n\n"
        f"## Hypotheses (unconfirmed)\n\n{bullets(h.get('hypotheses', []))}\n\n"
        f"## Reproduction\n\n{h.get('reproduction') or 'Not yet known.'}\n\n## Impact\n\n{h.get('impact') or 'Unknown.'}\n\n"
        f"## Computed facts\n\n- Accounts with this error signature in window: {facts.get('affected_accounts', 'n/a')}\n"
        f"- First seen for this account: {facts.get('first_seen_this_account', 'n/a')}\n\n"
        f"## Missing facts\n\n{bullets(h.get('missing_facts', []))}\n"
    )


def list_artifacts(db: Session, p: Principal, *, kind: str | None = None) -> list[tuple[Artifact, ArtifactVersion]]:
    stmt = scoped.artifacts(p)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    arts = list(db.execute(stmt.order_by(Artifact.created_at.desc()).limit(200)).scalars())
    out = []
    for a in arts:
        v = db.execute(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == a.id, ArtifactVersion.version == a.current_version
            )
        ).scalar_one()
        out.append((a, v))
    return out


def detail(db: Session, p: Principal, artifact_id: str) -> tuple[Artifact, list[ArtifactVersion]]:
    a = scoped.get_artifact(db, p, artifact_id)
    versions = list(
        db.execute(
            select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id).order_by(ArtifactVersion.version.desc())
        ).scalars()
    )
    return a, versions


def edit(db: Session, p: Principal, artifact_id: str, *, content: str, note: str | None) -> ArtifactVersion:
    """Free-standing edits (engineering briefs, incident summaries). Reply drafts are edited through review."""
    scoped.require_staff(p)
    a = scoped.get_artifact(db, p, artifact_id)
    if a.kind == "customer_reply":
        raise ValidationFailed("edit reply drafts from the review panel so the proposal is re-verified")
    if a.review_status == "approved":
        raise Conflict("approved artifacts are immutable")
    if not content.strip():
        raise ValidationFailed("content is empty")
    prev = db.execute(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id, ArtifactVersion.version == a.current_version)
    ).scalar_one()
    v = add_version(db, a, content=content, sources=prev.sources, verification=None, created_by=p.user_id, note=note)
    v.verification = {
        "status": "stale",
        "previous": prev.verification_status,
        "note": "edited after verification; re-run verification",
    }
    v.verification_status = "stale"
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="artifact.edited",
        target_type="artifact",
        target_id=a.id,
        detail={"version": v.version, "hash": v.content_hash},
    )
    return v


def revalidate(db: Session, p: Principal, artifact_id: str) -> ArtifactVersion:
    """Re-run the record checks that apply to a free-standing artifact and bind them to this content hash."""
    scoped.require_staff(p)
    a = scoped.get_artifact(db, p, artifact_id)
    v = db.execute(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id, ArtifactVersion.version == a.current_version)
    ).scalar_one()
    checks = []
    if a.kind == "incident_summary" and a.incident_id:
        inc = db.get(Incident, a.incident_id)
        links = db.execute(
            select(IncidentTicketLink, Ticket)
            .join(Ticket, Ticket.id == IncidentTicketLink.ticket_id)
            .where(IncidentTicketLink.incident_id == a.incident_id)
        ).all()
        accounts = len({t.customer_account_id for _, t in links})
        claimed = _claimed_count(v.content, "affected accounts")
        checks.append(
            {
                "name": "affected_account_count",
                "status": "pass" if claimed == accounts else "fail",
                "detail": f"content says {claimed}, records say {accounts}",
                "method": "record",
            }
        )
        checks.append(
            {
                "name": "incident_exists",
                "status": "pass" if inc else "fail",
                "detail": a.incident_id,
                "method": "record",
            }
        )
    import re

    from relayops.models import EngineeringIssue

    keys = set(re.findall(r"\b[A-Z]{2,5}-\d{1,5}\b", v.content))
    known = (
        set(
            db.execute(
                select(EngineeringIssue.key).where(
                    EngineeringIssue.organization_id == a.organization_id, EngineeringIssue.key.in_(keys)
                )
            ).scalars()
        )
        if keys
        else set()
    )
    checks.append(
        {
            "name": "issue_keys_exist",
            "status": "pass" if keys <= known else "fail",
            "detail": f"unknown keys: {sorted(keys - known)}" if keys - known else "ok",
            "method": "record",
        }
    )
    status = "failed" if any(c["status"] == "fail" for c in checks) else "passed"
    v.verification = {
        "status": status,
        "checks": checks,
        "verified_hash": v.content_hash,
        "note": "record checks only; claims are not semantically verified",
    }
    v.verification_status = status
    v.verified_content_hash = v.content_hash
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="artifact.revalidated",
        target_type="artifact",
        target_id=a.id,
        detail={"version": v.version, "status": status},
    )
    return v


def _claimed_count(text: str, label: str) -> int | None:
    import re

    m = re.search(rf"{label}\D{{0,20}}(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def export(db: Session, p: Principal, artifact_id: str, fmt: str) -> tuple[str, str, str]:
    a, versions = detail(db, p, artifact_id)
    current = versions[0]
    if fmt == "md":
        body = (
            f"<!-- RelayOps artifact {a.id} v{current.version} sha256:{current.content_hash} "
            f"verification:{current.verification_status} review:{a.review_status} -->\n\n{current.content}\n"
        )
        return body, "text/markdown; charset=utf-8", f"{a.id}-v{current.version}.md"
    if fmt == "json":
        body = json.dumps(
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "review_status": a.review_status,
                "ticket_id": a.ticket_id,
                "run_id": a.run_id,
                "versions": [
                    {
                        "version": v.version,
                        "content": v.content,
                        "content_hash": v.content_hash,
                        "verification_status": v.verification_status,
                        "verified_content_hash": v.verified_content_hash,
                        "sources": v.sources,
                        "created_by": v.created_by,
                        "created_at": v.created_at.isoformat(),
                        "note": v.note,
                    }
                    for v in versions
                ],
            },
            indent=2,
        )
        return body, "application/json", f"{a.id}.json"
    raise ValidationFailed("format must be md or json")
