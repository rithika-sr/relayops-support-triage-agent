"""Customer Success views computed from persisted records only.

- Onboarding: each step is complete when a qualifying record exists; its time is that record's time.
- Adoption and friction: per-account counts over a window, shown as separate signals rather than a score.
- Retention: weekly cohorts by an account's first customer activity. A week is reported only once every account
  in the cohort could have reached it; until then it is "pending", never 0%.
- Opportunities: documented rules with thresholds, each card listing the records behind it.

Counts include only the data classes analytics may count (operational, or the instance's own class).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.events import CUSTOMER_ACTIVITY
from relayops.domain.scope import Principal
from relayops.models import CustomerAccount, KnowledgeDocument, Membership, ProductEvent, Ticket
from relayops.repositories import scoped
from relayops.services.tickets import analytics_classes

STEPS = [
    ("signed_in", "Signed in to the portal", "user.signed_in"),
    ("first_ticket", "Submitted a first ticket", "ticket.created"),
    ("first_reply", "Received a reviewed reply", "reply.published"),
    ("used_help", "Read a Help article", "article.viewed"),
]
UNHELPFUL_MIN, UNHELPFUL_SHARE = 3, 0.5
ZERO_RESULT_MIN = 3
REPEAT_MIN, REPEAT_DAYS = 3, 30


def _events(db: Session, org: str, since: datetime | None = None, names: tuple[str, ...] | None = None) -> list[Any]:
    stmt = select(ProductEvent).where(
        ProductEvent.organization_id == org, ProductEvent.data_class.in_(analytics_classes())
    )
    if since is not None:
        stmt = stmt.where(ProductEvent.occurred_at >= since)
    if names:
        stmt = stmt.where(ProductEvent.name.in_(names))
    return list(db.execute(stmt.order_by(ProductEvent.occurred_at)).scalars())


def onboarding(db: Session, p: Principal, account_id: str) -> dict[str, Any]:
    acct = scoped.get_account(db, p, account_id)
    first: dict[str, datetime] = {}
    rows = db.execute(
        select(ProductEvent.name, func.min(ProductEvent.occurred_at))
        .where(
            ProductEvent.organization_id == acct.organization_id,
            ProductEvent.customer_account_id == acct.id,
            ProductEvent.data_class.in_(analytics_classes()),
        )
        .group_by(ProductEvent.name)
    ).all()
    first = {n: t for n, t in rows}
    members = db.execute(
        select(func.count(Membership.id), func.min(Membership.created_at)).where(
            Membership.customer_account_id == acct.id, Membership.role == "customer"
        )
    ).one()
    steps = [
        {
            "id": sid,
            "label": label,
            "done": name in first,
            "at": first[name].isoformat() if name in first else None,
            "basis": f"first {name} event",
        }
        for sid, label, name in STEPS
    ]
    steps.append(
        {
            "id": "teammate",
            "label": "Invited a teammate",
            "done": members[0] >= 2,
            "at": None,
            "basis": f"{members[0]} portal user(s) on the account",
        }
    )
    return {"account_id": acct.id, "steps": steps, "completed": sum(s["done"] for s in steps), "total": len(steps)}


def accounts(db: Session, p: Principal, days: int = 30) -> dict[str, Any]:
    scoped.require_staff(p)
    since = utcnow() - timedelta(days=days)
    evs = _events(db, p.organization_id, since)
    by: dict[str, Counter[str]] = defaultdict(Counter)
    zero: Counter[str] = Counter()
    for e in evs:
        if e.customer_account_id:
            by[e.customer_account_id][e.name] += 1
            if e.name == "help.searched" and e.properties.get("results") == 0:
                zero[e.customer_account_id] += 1
            if e.name == "article.feedback" and not e.properties.get("helpful"):
                by[e.customer_account_id]["unhelpful"] += 1
    classes = analytics_classes()
    tix = db.execute(
        select(Ticket.customer_account_id, Ticket.component, func.count(Ticket.id))
        .where(
            Ticket.organization_id == p.organization_id,
            Ticket.data_class.in_(classes),
            Ticket.created_at >= since,
            Ticket.is_historical.is_(False),
        )
        .group_by(Ticket.customer_account_id, Ticket.component)
    ).all()
    comp: dict[str, Counter[str]] = defaultdict(Counter)
    for acct, component_name, n in tix:
        comp[acct][component_name or "unassigned"] += n
    out = []
    for a in db.execute(scoped.accounts(p).order_by(CustomerAccount.name)).scalars():
        c = by.get(a.id, Counter())
        friction = []
        for component, n in comp.get(a.id, Counter()).items():
            if n >= REPEAT_MIN:
                friction.append(f"{n} tickets about {component} in {days} days")
        if zero.get(a.id, 0) >= ZERO_RESULT_MIN:
            friction.append(f"{zero[a.id]} Help searches found nothing")
        if c["unhelpful"]:
            friction.append(f"{c['unhelpful']} article(s) marked not helpful")
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "plan": a.plan,
                "tickets": sum(comp.get(a.id, Counter()).values()),
                "signins": c["user.signed_in"],
                "help_searches": c["help.searched"],
                "articles_read": c["article.viewed"],
                "escalations": c["help.escalated"],
                "friction": friction,
                "onboarding": onboarding(db, p, a.id)["completed"],
                "onboarding_total": len(STEPS) + 1,
            }
        )
    return {"window_days": days, "data_classes_included": list(classes), "accounts": out}


def retention(db: Session, p: Principal, weeks: int = 8) -> dict[str, Any]:
    scoped.require_staff(p)
    now = utcnow()
    evs = _events(db, p.organization_id, names=CUSTOMER_ACTIVITY)
    first: dict[str, datetime] = {}
    active: dict[str, set[int]] = defaultdict(set)
    for e in evs:
        if not e.customer_account_id:
            continue
        first.setdefault(e.customer_account_id, e.occurred_at)
    for e in evs:
        if e.customer_account_id:
            start = first[e.customer_account_id]
            active[e.customer_account_id].add((e.occurred_at - start).days // 7)
    cohorts: dict[str, list[str]] = defaultdict(list)
    for acct, t in first.items():
        monday = (t - timedelta(days=t.weekday())).date()
        cohorts[monday.isoformat()].append(acct)
    rows = []
    for week, accts in sorted(cohorts.items()):
        latest_start = max(first[a] for a in accts)
        cells = []
        for k in range(weeks):
            if latest_start + timedelta(weeks=k + 1) > now:
                cells.append({"week": k, "status": "pending"})
            else:
                n = sum(1 for a in accts if k in active[a])
                cells.append(
                    {
                        "week": k,
                        "status": "measured",
                        "active": n,
                        "eligible": len(accts),
                        "rate": round(n / len(accts), 3),
                    }
                )
        rows.append({"cohort_week": week, "accounts": len(accts), "weeks": cells})
    return {
        "cohorts": rows,
        "activity_events": list(CUSTOMER_ACTIVITY),
        "data_classes_included": list(analytics_classes()),
        "note": "Week k is measured only after every account in the cohort has had k+1 full weeks.",
    }


def _norm(q: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", q.lower()))[:60]


def opportunities(db: Session, p: Principal, days: int = 30) -> dict[str, Any]:
    scoped.require_staff(p)
    since = utcnow() - timedelta(days=days)
    evs = _events(db, p.organization_id, since, ("article.feedback", "help.searched", "help.escalated"))
    cards: list[dict[str, Any]] = []
    latest: dict[tuple[str | None, str], bool] = {}
    for e in evs:
        if e.name == "article.feedback":
            latest[(e.actor_user_id, e.properties["document_id"])] = e.properties["helpful"]
    per_doc: dict[str, list[bool]] = defaultdict(list)
    for (_, doc), helpful in latest.items():
        per_doc[doc].append(helpful)
    titles = dict(
        db.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.title).where(
                KnowledgeDocument.organization_id == p.organization_id
            )
        ).all()
    )
    for doc, votes in per_doc.items():
        bad = votes.count(False)
        if len(votes) >= UNHELPFUL_MIN and bad / len(votes) >= UNHELPFUL_SHARE:
            cards.append(
                {
                    "kind": "improve_article",
                    "title": f"Review “{titles.get(doc, doc)}”",
                    "evidence": f"{bad} of {len(votes)} readers said it did not help (latest vote per reader)",
                    "rule": f"≥{UNHELPFUL_MIN} votes and ≥{int(UNHELPFUL_SHARE * 100)}% not helpful",
                    "target": {"document_id": doc},
                }
            )
    zero: Counter[str] = Counter(
        _norm(e.properties["query"]) for e in evs if e.name == "help.searched" and e.properties.get("results") == 0
    )
    for q, n in zero.most_common(5):
        if n >= ZERO_RESULT_MIN and q:
            cards.append(
                {
                    "kind": "knowledge_gap",
                    "title": f"Write Help for “{q}”",
                    "evidence": f"{n} searches returned no articles",
                    "rule": f"≥{ZERO_RESULT_MIN} zero-result searches",
                    "target": {"query": q},
                }
            )
    tix = db.execute(
        select(Ticket.customer_account_id, Ticket.component, func.count(Ticket.id))
        .where(
            Ticket.organization_id == p.organization_id,
            Ticket.data_class.in_(analytics_classes()),
            Ticket.created_at >= utcnow() - timedelta(days=REPEAT_DAYS),
            Ticket.component.is_not(None),
            Ticket.is_historical.is_(False),
        )
        .group_by(Ticket.customer_account_id, Ticket.component)
        .having(func.count(Ticket.id) >= REPEAT_MIN)
    ).all()
    names = dict(
        db.execute(
            select(CustomerAccount.id, CustomerAccount.name).where(CustomerAccount.organization_id == p.organization_id)
        ).all()
    )
    for acct, component, n in tix:
        cards.append(
            {
                "kind": "reach_out",
                "title": f"Check in with {names.get(acct, acct)} about {component}",
                "evidence": f"{n} tickets about {component} in {REPEAT_DAYS} days",
                "rule": f"≥{REPEAT_MIN} tickets on one component in {REPEAT_DAYS} days",
                "target": {"account_id": acct, "component": component},
            }
        )
    return {"cards": cards, "window_days": days, "data_classes_included": list(analytics_classes())}
