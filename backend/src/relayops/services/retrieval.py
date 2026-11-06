"""Authorized retrieval with lexical-only, dense-only, and RRF modes.

All three modes share `_authorized_chunks`, so authorization, version currency, and validity windows are
identical across baselines. Lexical ranking is PostgreSQL `ts_rank_cd`, which is not BM25.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, and_, func, literal, or_, select, text
from sqlalchemy.orm import Session

from relayops.agents.llm import ModelUnavailable, Provider, get_provider
from relayops.core.clock import utcnow
from relayops.domain.scope import Principal
from relayops.models import DocumentVersion, KnowledgeChunk, KnowledgeDocument

Mode = Literal["lexical", "dense", "rrf"]
AUTHORITY = {"policy": 3, "release_note": 2, "article": 2, "runbook": 2, "historical_case": 1}
_STOP = set(
    "a an and are as at be but by for from has have how i if in is it its my of on or our so that the this to "
    "we what when where which why with you your".split()
)


@dataclass(frozen=True)
class RetrievalScope:
    """Trusted scope. Built from a principal or from a server-side investigation context, never from model output."""

    organization_id: str
    customer_account_id: str | None
    audience: Literal["staff", "customer"]

    @classmethod
    def for_principal(cls, p: Principal, account_id: str | None = None) -> RetrievalScope:
        if p.is_staff:
            return cls(p.organization_id, account_id, "staff")
        return cls(p.organization_id, p.customer_account_id, "customer")


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    document_version_id: str
    version: int
    slug: str
    title: str
    kind: str
    visibility: str
    component: str | None
    product_versions: list[str]
    heading: str
    text: str
    content_hash: str
    valid_from: str | None
    valid_to: str | None
    authority: int
    score: float
    ranks: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _tokens(query: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if t not in _STOP and len(t) > 1]
    return list(dict.fromkeys(toks))[:24]


def _authorized_chunks(
    scope: RetrievalScope, *, as_of: datetime, kinds: tuple[str, ...] | None
) -> Select[KnowledgeChunk, KnowledgeDocument, DocumentVersion]:
    conds = [
        KnowledgeChunk.organization_id == scope.organization_id,
        KnowledgeDocument.status == "current",
        KnowledgeDocument.current_version_id == KnowledgeChunk.document_version_id,
        or_(DocumentVersion.valid_from.is_(None), DocumentVersion.valid_from <= as_of),
        or_(DocumentVersion.valid_to.is_(None), DocumentVersion.valid_to > as_of),
    ]
    if scope.customer_account_id:
        conds.append(
            or_(
                KnowledgeDocument.customer_account_id.is_(None),
                KnowledgeDocument.customer_account_id == scope.customer_account_id,
            )
        )
    else:
        conds.append(KnowledgeDocument.customer_account_id.is_(None))
    if scope.audience == "customer":
        conds += [KnowledgeDocument.visibility == "public", KnowledgeDocument.kind != "historical_case"]
    if kinds:
        conds.append(KnowledgeDocument.kind.in_(kinds))
    return (
        select(KnowledgeChunk, KnowledgeDocument, DocumentVersion)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == KnowledgeChunk.document_version_id)
        .where(and_(*conds))
    )


def _hit(c: KnowledgeChunk, d: KnowledgeDocument, v: DocumentVersion, score: float) -> Hit:
    return Hit(
        chunk_id=c.id,
        document_id=d.id,
        document_version_id=v.id,
        version=v.version,
        slug=d.slug,
        title=d.title,
        kind=d.kind,
        visibility=d.visibility,
        component=d.component,
        product_versions=list(d.product_versions or []),
        heading=c.heading,
        text=c.text,
        content_hash=c.content_hash,
        valid_from=v.valid_from.isoformat() if v.valid_from else None,
        valid_to=v.valid_to.isoformat() if v.valid_to else None,
        authority=AUTHORITY.get(d.kind, 1),
        score=float(score),
    )


def lexical(
    db: Session,
    scope: RetrievalScope,
    query: str,
    *,
    k: int,
    as_of: datetime,
    kinds: tuple[str, ...] | None = None,
    component: str | None = None,
) -> list[Hit]:
    toks = _tokens(query)
    if not toks:
        return []
    tsq = func.to_tsquery("english", literal(" | ".join(toks)))
    rank = func.ts_rank_cd(KnowledgeChunk.tsv, tsq, 32)
    stmt = (
        _authorized_chunks(scope, as_of=as_of, kinds=kinds)
        .add_columns(rank.label("rank"))
        .where(KnowledgeChunk.tsv.op("@@")(tsq))
    )
    if component:
        stmt = stmt.where(or_(KnowledgeDocument.component == component, KnowledgeDocument.component.is_(None)))
    rows = db.execute(stmt.order_by(text("rank DESC"), KnowledgeChunk.id).limit(k)).all()
    return [_hit(c, d, v, r) for c, d, v, r in rows]


def dense(
    db: Session,
    scope: RetrievalScope,
    query: str,
    *,
    k: int,
    as_of: datetime,
    kinds: tuple[str, ...] | None = None,
    component: str | None = None,
    provider: Provider | None = None,
) -> list[Hit]:
    provider = provider or get_provider()
    [qvec] = provider.embed([query])
    dist = KnowledgeChunk.embedding.cosine_distance(qvec)
    stmt = (
        _authorized_chunks(scope, as_of=as_of, kinds=kinds)
        .add_columns(dist.label("dist"))
        .where(KnowledgeChunk.embedding.is_not(None), KnowledgeChunk.embedding_model == provider.embed_model)
    )
    if component:
        stmt = stmt.where(or_(KnowledgeDocument.component == component, KnowledgeDocument.component.is_(None)))
    rows = db.execute(stmt.order_by(text("dist ASC"), KnowledgeChunk.id).limit(k)).all()
    return [_hit(c, d, v, 1.0 - float(dist_)) for c, d, v, dist_ in rows]


def embedding_model_guard(db: Session, organization_id: str, provider: Provider) -> dict[str, Any]:
    rows = db.execute(
        select(KnowledgeChunk.embedding_model, func.count(KnowledgeChunk.id))
        .where(KnowledgeChunk.organization_id == organization_id)
        .group_by(KnowledgeChunk.embedding_model)
    ).all()
    models = {m: int(c) for m, c in rows}
    return {
        "index_models": models,
        "provider_model": provider.embed_model,
        "compatible": provider.embed_model in models and len(models) == 1,
    }


def search(
    db: Session,
    scope: RetrievalScope,
    query: str,
    *,
    mode: Mode = "rrf",
    k: int = 5,
    as_of: datetime | None = None,
    kinds: tuple[str, ...] | None = None,
    component: str | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    as_of = as_of or utcnow()
    pool = max(k * 3, 10)
    out: dict[str, Any] = {"mode": mode, "k": k, "as_of": as_of.isoformat(), "lexical_engine": "postgres ts_rank_cd"}
    lex = lexical(db, scope, query, k=pool, as_of=as_of, kinds=kinds, component=component) if mode != "dense" else []
    den: list[Hit] = []
    if mode != "lexical":
        try:
            den = dense(db, scope, query, k=pool, as_of=as_of, kinds=kinds, component=component, provider=provider)
        except ModelUnavailable as exc:
            if mode == "dense":
                raise
            out["dense_error"] = str(exc)
    if mode == "lexical":
        ranked = lex
        for i, h in enumerate(ranked):
            h.ranks["lexical"] = i + 1
    elif mode == "dense":
        ranked = den
        for i, h in enumerate(ranked):
            h.ranks["dense"] = i + 1
    else:
        fused: dict[str, Hit] = {}
        scores: dict[str, float] = {}
        for name, hits in (("lexical", lex), ("dense", den)):
            for i, h in enumerate(hits):
                cur = fused.setdefault(h.chunk_id, h)
                cur.ranks[name] = i + 1
                scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (60 + i + 1)
        ranked = list(fused.values())
        for h in ranked:
            h.score = scores[h.chunk_id]
    # Authority boost: current policy outranks articles, which outrank historical examples.
    for h in ranked:
        h.score = h.score * (1 + 0.25 * h.authority)
    ranked.sort(key=lambda h: (-h.score, h.chunk_id))
    out["results"] = [h.as_dict() for h in ranked[:k]]
    return out
