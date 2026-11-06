"""Customer self-service Help: search current public knowledge, read an article, say whether it helped, and
contact support with the context carried over. Each step is recorded as a product event."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy.orm import Session

from relayops.domain.scope import AccessDenied, Principal, ValidationFailed
from relayops.models import DocumentVersion, KnowledgeDocument
from relayops.repositories import scoped
from relayops.services import events, experiments, retrieval
from relayops.services import tickets as ticket_service


def _customer(p: Principal) -> None:
    if p.is_staff or not p.customer_account_id:
        raise AccessDenied("Help is the customer portal; staff use Knowledge")


def search(db: Session, p: Principal, q: str) -> dict[str, Any]:
    _customer(p)
    q = q.strip()
    if not 2 <= len(q) <= 200:
        raise ValidationFailed("search for 2-200 characters")
    mode, exp = "rrf", experiments.running(db, p.organization_id)
    if exp is not None:
        assert p.customer_account_id
        mode = experiments.assign(exp.key, p.customer_account_id, exp.variants)
        events.for_principal(
            db,
            p,
            "experiment.exposed",
            {"experiment": exp.key, "variant": mode},
            event_id=f"experiment.exposed:{exp.key}:{p.customer_account_id}",
        )
    res = retrieval.search(
        db,
        retrieval.RetrievalScope.for_principal(p),
        q,
        mode=cast(retrieval.Mode, mode),
        k=8,  # type: ignore[arg-type]
        kinds=("article", "policy", "release_note", "runbook"),
    )
    seen: dict[str, dict[str, Any]] = {}
    for h in res["results"]:
        if h["visibility"] == "public" and h["document_id"] not in seen:
            seen[h["document_id"]] = {
                "document_id": h["document_id"],
                "title": h["title"],
                "kind": h["kind"],
                "excerpt": h["text"][:280],
            }
    results = list(seen.values())[:5]
    events.for_principal(db, p, "help.searched", {"query": q, "results": len(results)})
    return {"query": q, "results": results, "ranking": mode if exp else None}


def article(db: Session, p: Principal, document_id: str) -> dict[str, Any]:
    _customer(p)
    doc = scoped.one(
        db,
        scoped.documents(p).where(KnowledgeDocument.id == document_id, KnowledgeDocument.status == "current"),
        "article",
    )
    v = db.get(DocumentVersion, doc.current_version_id) if doc.current_version_id else None
    if v is None:
        raise ValidationFailed("article has no current version")
    events.for_principal(
        db,
        p,
        "article.viewed",
        {"document_id": doc.id},
        event_id=f"article.viewed:{p.user_id}:{doc.id}:{date.today().isoformat()}",
    )
    return {
        "document_id": doc.id,
        "title": doc.title,
        "kind": doc.kind,
        "content": v.content,
        "version": v.version,
        "updated_at": v.created_at.isoformat(),
    }


def feedback(db: Session, p: Principal, document_id: str, helpful: bool) -> dict[str, Any]:
    _customer(p)
    doc = scoped.one(db, scoped.documents(p).where(KnowledgeDocument.id == document_id), "article")
    events.for_principal(db, p, "article.feedback", {"document_id": doc.id, "helpful": helpful})
    return {"recorded": True}


def escalate(
    db: Session, p: Principal, *, subject: str, body: str, document_id: str | None, query: str | None
) -> dict[str, Any]:
    _customer(p)
    if document_id:
        scoped.one(db, scoped.documents(p).where(KnowledgeDocument.id == document_id), "article")
    ticket, _ = ticket_service.create_ticket(db, p, ticket_service.TicketInput(subject=subject, body=body))
    props: dict[str, Any] = {"ticket_id": ticket.id}
    if document_id:
        props["document_id"] = document_id
    if query:
        props["query"] = query.strip()
    events.for_principal(db, p, "help.escalated", props, event_id=f"help.escalated:{ticket.id}")
    return {"ticket_id": ticket.id, "number": ticket.number}
