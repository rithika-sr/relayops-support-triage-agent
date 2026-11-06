"""A small, honest experiment framework for one surface: how the customer Help search ranks results.

Assignment is deterministic per customer account (hash of experiment key and account). An account is exposed
the first time it searches Help while the experiment runs. The metric is the share of searching accounts that
contacted support from Help within the experiment window. Results stay "insufficient sample" until every
variant reaches its pre-registered minimum; only then is a difference and a 95% interval shown. The decision
is meant to be made once, at the planned stop, not by watching the interval.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.scope import Conflict, Principal, ValidationFailed
from relayops.models import Experiment, ProductEvent
from relayops.repositories import scoped
from relayops.services import audit

SURFACE_VARIANTS = ("lexical", "rrf")  # Help search ranking modes the surface can serve
METRICS = ("help_escalation_rate",)
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")


def assign(key: str, account_id: str, variants: list[str]) -> str:
    h = int(hashlib.sha256(f"{key}:{account_id}".encode()).hexdigest(), 16)
    return variants[h % len(variants)]


def running(db: Session, organization_id: str) -> Experiment | None:
    return (
        db.execute(
            select(Experiment).where(Experiment.organization_id == organization_id, Experiment.status == "running")
        )
        .scalars()
        .first()
    )


def as_dict(e: Experiment) -> dict[str, Any]:
    return {
        "id": e.id,
        "key": e.key,
        "hypothesis": e.hypothesis,
        "metric": e.metric,
        "variants": e.variants,
        "min_accounts_per_variant": e.min_accounts_per_variant,
        "status": e.status,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "stopped_at": e.stopped_at.isoformat() if e.stopped_at else None,
    }


def create(
    db: Session, p: Principal, *, key: str, hypothesis: str, variants: list[str], min_accounts_per_variant: int
) -> Experiment:
    scoped.require_admin(p)
    if not KEY.match(key):
        raise ValidationFailed("key: 3-60 lowercase letters, digits, or dashes")
    if len(hypothesis.strip()) < 20:
        raise ValidationFailed("write the hypothesis before starting (at least 20 characters)")
    if len(set(variants)) != len(variants) or len(variants) < 2 or not set(variants) <= set(SURFACE_VARIANTS):
        raise ValidationFailed(f"variants must be two or more of {', '.join(SURFACE_VARIANTS)}")
    if not 10 <= min_accounts_per_variant <= 100_000:
        raise ValidationFailed("minimum accounts per variant must be between 10 and 100,000")
    if db.execute(
        select(Experiment.id).where(Experiment.organization_id == p.organization_id, Experiment.key == key)
    ).first():
        raise Conflict("an experiment with this key exists")
    e = Experiment(
        organization_id=p.organization_id,
        key=key,
        hypothesis=hypothesis.strip(),
        metric="help_escalation_rate",
        variants=variants,
        min_accounts_per_variant=min_accounts_per_variant,
        created_by_user_id=p.user_id,
    )
    db.add(e)
    db.flush()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="experiment.created",
        target_type="experiment",
        target_id=e.id,
        detail=as_dict(e),
    )
    return e


def transition(db: Session, p: Principal, experiment_id: str, action: str) -> Experiment:
    scoped.require_admin(p)
    e = db.execute(
        select(Experiment).where(Experiment.id == experiment_id, Experiment.organization_id == p.organization_id)
    ).scalar_one_or_none()
    if e is None:
        raise ValidationFailed("experiment not found")
    if action == "start":
        if e.status != "draft":
            raise Conflict("only a draft experiment can start; a stopped one cannot restart")
        if running(db, p.organization_id):
            raise Conflict("another experiment is running on this surface")
        e.status, e.started_at = "running", utcnow()
    elif action == "stop":
        if e.status != "running":
            raise Conflict("experiment is not running")
        e.status, e.stopped_at = "stopped", utcnow()
    else:
        raise ValidationFailed("action must be start or stop")
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action=f"experiment.{action}",
        target_type="experiment",
        target_id=e.id,
    )
    return e


def results(db: Session, p: Principal, e: Experiment, classes: tuple[str, ...]) -> dict[str, Any]:
    scoped.require_staff(p)
    if e.started_at is None:
        return {"status": "not_started"}
    end = e.stopped_at or utcnow()
    rows = db.execute(
        select(ProductEvent.customer_account_id, ProductEvent.name, ProductEvent.properties).where(
            ProductEvent.organization_id == e.organization_id,
            ProductEvent.data_class.in_(classes),
            ProductEvent.occurred_at >= e.started_at,
            ProductEvent.occurred_at <= end,
            ProductEvent.name.in_(("experiment.exposed", "help.escalated")),
        )
    ).all()
    exposed: dict[str, str] = {}
    escalated: set[str] = set()
    for acct, name, props in rows:
        if acct is None:
            continue
        if name == "experiment.exposed" and props.get("experiment") == e.key:
            exposed.setdefault(acct, props["variant"])
        elif name == "help.escalated":
            escalated.add(acct)
    per: dict[str, dict[str, Any]] = {}
    for v in e.variants:
        accts = [a for a, var in exposed.items() if var == v]
        n, k = len(accts), sum(1 for a in accts if a in escalated)
        per[v] = {"accounts": n, "escalated": k, "rate": round(k / n, 4) if n else None}
    enough = all(per[v]["accounts"] >= e.min_accounts_per_variant for v in e.variants)
    out: dict[str, Any] = {
        "status": "insufficient_sample" if not enough else "measured",
        "variants": per,
        "min_accounts_per_variant": e.min_accounts_per_variant,
        "note": "Fixed-horizon design: decide at the planned stop, not by watching the interval.",
    }
    if enough and len(e.variants) == 2:
        a, b = (per[v] for v in e.variants)
        pa, pb = a["escalated"] / a["accounts"], b["escalated"] / b["accounts"]
        se = math.sqrt(pa * (1 - pa) / a["accounts"] + pb * (1 - pb) / b["accounts"])
        diff = pb - pa
        out["difference"] = {
            "of": f"{e.variants[1]} minus {e.variants[0]}",
            "estimate": round(diff, 4),
            "ci95": [round(diff - 1.96 * se, 4), round(diff + 1.96 * se, 4)],
            "method": "normal approximation for a difference of proportions",
        }
    return out
