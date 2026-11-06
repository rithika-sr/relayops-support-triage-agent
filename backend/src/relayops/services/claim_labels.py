"""Human labels on reply claims, kept apart from automated verdicts.

Labels are immutable; the latest label per (claim, annotator) counts. When annotators disagree the claim is
reported as a disagreement and is left out of agreement statistics. Statistics are "pending" until real labels
exist; nothing here infers or fills in a human judgment.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import ANNOTATION_VERDICTS, ClaimAnnotation, Proposal
from relayops.repositories import scoped
from relayops.services import audit
from relayops.services.tickets import analytics_classes

MAX_IMPORT = 2000


def claim_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _claim(prop: Proposal, index: int) -> dict[str, Any]:
    claims = prop.verification.get("claims") or []
    if not 0 <= index < len(claims):
        raise ValidationFailed(f"proposal has no claim {index}")
    return claims[index]


def _dedupe(prop_id: str, index: int, annotator: str, verdict: str, note: str | None, seq: str) -> str:
    return hashlib.sha256(json.dumps([prop_id, index, annotator, verdict, note or "", seq]).encode()).hexdigest()


def _add(
    db: Session,
    p: Principal,
    prop: Proposal,
    index: int,
    verdict: str,
    note: str | None,
    *,
    annotator: str,
    source: str,
    expected_sha: str | None,
    seq: str,
) -> ClaimAnnotation | None:
    if verdict not in ANNOTATION_VERDICTS:
        raise ValidationFailed(f"verdict must be one of {', '.join(ANNOTATION_VERDICTS)}")
    claim = _claim(prop, index)
    sha = claim_sha(claim["text"])
    if expected_sha is not None and expected_sha != sha:
        raise ValidationFailed(f"claim {index} text does not match the labeled text")
    key = _dedupe(prop.id, index, annotator, verdict, note, seq)
    if db.execute(select(ClaimAnnotation.id).where(ClaimAnnotation.dedupe_key == key)).first():
        return None
    row = ClaimAnnotation(
        organization_id=prop.organization_id,
        proposal_id=prop.id,
        claim_index=index,
        claim_sha256=sha,
        verdict=verdict,
        note=note,
        annotator_key=annotator,
        recorded_by_user_id=p.user_id,
        source=source,
        dedupe_key=key,
        data_class=prop.data_class,
    )
    db.add(row)
    db.flush()
    return row


def annotate(
    db: Session, p: Principal, proposal_id: str, index: int, *, verdict: str, note: str | None, expected_sha: str
) -> ClaimAnnotation:
    scoped.require_staff(p)
    prop = scoped.get_proposal(db, p, proposal_id)
    n = db.query(ClaimAnnotation).filter_by(proposal_id=prop.id, claim_index=index, annotator_key=p.user_id).count()
    row = _add(
        db, p, prop, index, verdict, note, annotator=p.user_id, source="ui", expected_sha=expected_sha, seq=str(n)
    )
    assert row is not None
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="claim.annotated",
        target_type="proposal",
        target_id=prop.id,
        detail={"claim_index": index, "verdict": verdict},
    )
    return row


def _latest(rows: list[ClaimAnnotation]) -> dict[tuple[str, int], dict[str, ClaimAnnotation]]:
    out: dict[tuple[str, int], dict[str, ClaimAnnotation]] = defaultdict(dict)
    for r in sorted(rows, key=lambda r: (r.created_at, r.id)):
        out[(r.proposal_id, r.claim_index)][r.annotator_key] = r
    return out


def for_proposal(db: Session, p: Principal, proposal_id: str) -> list[dict[str, Any]]:
    scoped.require_staff(p)
    prop = scoped.get_proposal(db, p, proposal_id)
    rows = list(db.execute(select(ClaimAnnotation).where(ClaimAnnotation.proposal_id == prop.id)).scalars())
    latest = _latest(rows)
    out = []
    for (_, idx), by in sorted(latest.items()):
        verdicts = {r.verdict for r in by.values()}
        out.append(
            {
                "claim_index": idx,
                "labels": [
                    {
                        "annotator": k,
                        "verdict": r.verdict,
                        "note": r.note,
                        "source": r.source,
                        "at": r.created_at.isoformat(),
                    }
                    for k, r in by.items()
                ],
                "consensus": verdicts.pop() if len(verdicts) == 1 else "disagreement",
            }
        )
    return out


def export(db: Session, p: Principal) -> list[dict[str, Any]]:
    scoped.require_staff(p)
    rows = db.execute(
        select(ClaimAnnotation)
        .where(ClaimAnnotation.organization_id == p.organization_id)
        .order_by(ClaimAnnotation.created_at, ClaimAnnotation.id)
    ).scalars()
    return [
        {
            "proposal_id": r.proposal_id,
            "claim_index": r.claim_index,
            "claim_sha256": r.claim_sha256,
            "verdict": r.verdict,
            "note": r.note,
            "annotator": r.annotator_key,
            "source": r.source,
            "data_class": r.data_class,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def import_labels(
    db: Session, p: Principal, items: list[dict[str, Any]], *, annotator_label: str, dry_run: bool
) -> dict[str, Any]:
    """Import labels made outside the app. Each must name the claim by proposal, index, and text hash."""
    scoped.require_admin(p)
    if not annotator_label.strip() or len(annotator_label) > 80:
        raise ValidationFailed("annotator_label is required (max 80 characters)")
    if len(items) > MAX_IMPORT:
        raise ValidationFailed(f"at most {MAX_IMPORT} labels per import")
    created = duplicates = 0
    errors: list[dict[str, Any]] = []
    with db.begin_nested() as sp:
        for i, it in enumerate(items):
            try:
                prop = scoped.get_proposal(db, p, str(it.get("proposal_id", "")))
                row = _add(
                    db,
                    p,
                    prop,
                    int(it.get("claim_index", -1)),
                    str(it.get("verdict", "")),
                    it.get("note"),
                    annotator=f"import:{annotator_label.strip()}",
                    source="import",
                    expected_sha=str(it.get("claim_sha256", "")),
                    seq=str(it.get("seq", 0)),
                )
                created += row is not None
                duplicates += row is None
            except (ValidationFailed, scoped.NotFound, ValueError, TypeError) as exc:
                errors.append({"row": i, "error": str(exc)})
        if dry_run or errors:
            sp.rollback()
    if not dry_run and not errors:
        audit.record(
            db,
            organization_id=p.organization_id,
            actor=p,
            action="claim.labels_imported",
            target_type="organization",
            target_id=p.organization_id,
            detail={"created": created, "duplicates": duplicates, "annotator": annotator_label},
        )
    return {
        "dry_run": dry_run,
        "committed": not dry_run and not errors,
        "created": created if not errors else 0,
        "duplicates": duplicates,
        "errors": errors,
    }


def stats(db: Session, p: Principal) -> dict[str, Any]:
    """Agreement between automated verdicts and human consensus, only over real labels."""
    scoped.require_staff(p)
    classes = analytics_classes()
    rows = list(
        db.execute(
            select(ClaimAnnotation).where(
                ClaimAnnotation.organization_id == p.organization_id, ClaimAnnotation.data_class.in_(classes)
            )
        ).scalars()
    )
    if not rows:
        return {
            "status": "pending",
            "annotated_claims": 0,
            "data_classes_included": list(classes),
            "note": "No human labels yet. Agreement is not estimated without them.",
        }
    latest = _latest(rows)
    props = {pr.id: pr for pr in db.execute(select(Proposal).where(Proposal.id.in_({k[0] for k in latest}))).scalars()}
    by_method: dict[str, dict[str, int]] = defaultdict(lambda: {"agree": 0, "disagree": 0})
    disagreements = stale = 0
    for (pid, idx), by in latest.items():
        verdicts = {r.verdict for r in by.values()}
        if len(verdicts) > 1:
            disagreements += 1
            continue
        claim = (props[pid].verification.get("claims") or [])[idx]
        if claim_sha(claim["text"]) != next(iter(by.values())).claim_sha256:
            stale += 1
            continue
        human = verdicts.pop()
        by_method[claim["method"]]["agree" if claim["verdict"] == human else "disagree"] += 1
    return {
        "status": "measured",
        "annotated_claims": len(latest),
        "annotator_disagreements": disagreements,
        "stale_labels": stale,
        "by_method": dict(by_method),
        "data_classes_included": list(classes),
        "note": "Counts, not rates; small samples say little. Disagreements are excluded from agreement.",
    }
