"""Versioned, scoped knowledge ingestion and heading-aware chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.agents.llm import Provider, get_provider
from relayops.core.clock import utcnow
from relayops.core.security import content_hash
from relayops.domain.policies import COMPONENTS
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import DocumentVersion, KnowledgeChunk, KnowledgeDocument, Organization
from relayops.repositories import scoped
from relayops.services import audit

KINDS = ("policy", "article", "historical_case", "runbook", "release_note")
VISIBILITIES = ("public", "internal")
MAX_CHUNK_CHARS = 1200
MAX_DOC_BYTES = 200_000


@dataclass(frozen=True)
class DocumentInput:
    slug: str
    title: str
    kind: str
    visibility: str
    content: str
    component: str | None = None
    product_versions: tuple[str, ...] = ()
    customer_account_id: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    media_type: str = "text/markdown"
    source_filename: str | None = None


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split on Markdown headings, then on paragraph boundaries to stay under MAX_CHUNK_CHARS."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    out: list[tuple[str, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        buf = ""
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if buf and len(buf) + len(para) + 2 > MAX_CHUNK_CHARS:
                out.append((heading, buf))
                buf = ""
            buf = f"{buf}\n\n{para}" if buf else para
            while len(buf) > MAX_CHUNK_CHARS:
                out.append((heading, buf[:MAX_CHUNK_CHARS]))
                buf = buf[MAX_CHUNK_CHARS:]
        if buf:
            out.append((heading, buf))
    return out


def _validate(inp: DocumentInput) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,158}", inp.slug):
        raise ValidationFailed("slug must be lowercase letters, digits, and dashes")
    if inp.kind not in KINDS:
        raise ValidationFailed("unknown document kind")
    if inp.visibility not in VISIBILITIES:
        raise ValidationFailed("unknown visibility")
    if inp.component and inp.component not in COMPONENTS:
        raise ValidationFailed("unknown component")
    if not inp.title.strip():
        raise ValidationFailed("title is required")
    if not inp.content.strip():
        raise ValidationFailed("document is empty")
    if len(inp.content.encode()) > MAX_DOC_BYTES:
        raise ValidationFailed("document exceeds 200 KB")
    if inp.kind == "historical_case" and inp.visibility != "internal":
        raise ValidationFailed("historical cases are internal-only")
    if inp.valid_from and inp.valid_to and inp.valid_to <= inp.valid_from:
        raise ValidationFailed("valid_to must be after valid_from")


def ingest(
    db: Session,
    p: Principal | None,
    inp: DocumentInput,
    *,
    organization_id: str | None = None,
    provider: Provider | None = None,
) -> tuple[KnowledgeDocument, DocumentVersion, bool]:
    """Create a document or a new version of it. Returns (doc, version, changed).

    Embeddings are computed before any rows are written, so a model failure leaves no partial index.
    """
    if p is not None:
        scoped.require_staff(p)
        organization_id = p.organization_id
    assert organization_id
    _validate(inp)
    if inp.customer_account_id and p is not None:
        scoped.get_account(db, p, inp.customer_account_id)

    digest = content_hash(inp.content)
    doc = db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == organization_id, KnowledgeDocument.slug == inp.slug
        )
    ).scalar_one_or_none()
    if doc is not None and doc.current_version_id:
        current = db.get(DocumentVersion, doc.current_version_id)
        if current is not None and current.content_hash == digest:
            return doc, current, False

    pieces = chunk_markdown(inp.content) if inp.media_type == "text/markdown" else [("", inp.content.strip())]
    provider = provider or get_provider()
    vectors = provider.embed([f"{inp.title}\n{h}\n{t}" for h, t in pieces])

    now = utcnow()
    if doc is None:
        org = db.get(Organization, organization_id)
        doc = KnowledgeDocument(
            organization_id=organization_id,
            slug=inp.slug,
            title=inp.title.strip(),
            data_class=org.data_class if org else "unknown",
            source_kind="manual" if p is not None else "seed",
        )
        db.add(doc)
    doc.title = inp.title.strip()
    doc.kind = inp.kind
    doc.visibility = inp.visibility
    doc.component = inp.component
    doc.product_versions = list(inp.product_versions)
    doc.customer_account_id = inp.customer_account_id
    doc.status = "current"
    db.flush()

    prev_version = 0
    if doc.current_version_id:
        prev = db.get(DocumentVersion, doc.current_version_id)
        if prev is not None:
            prev_version = prev.version
            if prev.valid_to is None or prev.valid_to > now:
                prev.valid_to = inp.valid_from or now
    version = DocumentVersion(
        document_id=doc.id,
        organization_id=organization_id,
        version=prev_version + 1,
        content=inp.content,
        content_hash=digest,
        media_type=inp.media_type,
        source_filename=inp.source_filename,
        valid_from=inp.valid_from or now,
        valid_to=inp.valid_to,
        created_by_user_id=p.user_id if p else None,
    )
    db.add(version)
    db.flush()
    for i, ((heading, text), vec) in enumerate(zip(pieces, vectors, strict=True)):
        db.add(
            KnowledgeChunk(
                document_version_id=version.id,
                document_id=doc.id,
                organization_id=organization_id,
                ordinal=i,
                heading=heading[:300],
                text=text,
                content_hash=content_hash(text),
                embedding=vec,
                embedding_model=provider.embed_model,
            )
        )
    doc.current_version_id = version.id
    db.flush()
    audit.record(
        db,
        organization_id=organization_id,
        actor=p,
        action="knowledge.version_created",
        target_type="document",
        target_id=doc.id,
        detail={"slug": doc.slug, "version": version.version, "hash": digest, "chunks": len(pieces)},
    )
    return doc, version, True


def set_status(db: Session, p: Principal, doc_id: str, status: str) -> KnowledgeDocument:
    scoped.require_staff(p)
    if status not in ("current", "superseded", "retired"):
        raise ValidationFailed("unknown status")
    doc = scoped.get_document(db, p, doc_id)
    before = doc.status
    doc.status = status
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="knowledge.status_changed",
        target_type="document",
        target_id=doc.id,
        detail={"before": before, "after": status},
    )
    return doc


def list_documents(
    db: Session, p: Principal, *, kind: str | None = None, status: str | None = None, q: str | None = None
) -> list[tuple[KnowledgeDocument, DocumentVersion | None, int]]:
    stmt = scoped.documents(p)
    if kind:
        stmt = stmt.where(KnowledgeDocument.kind == kind)
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    if q:
        stmt = stmt.where(KnowledgeDocument.title.ilike(f"%{q[:100]}%"))
    docs = list(db.execute(stmt.order_by(KnowledgeDocument.kind, KnowledgeDocument.title)).scalars())
    versions = {
        v.id: v
        for v in db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id.in_([d.current_version_id for d in docs if d.current_version_id])
            )
        ).scalars()
    }
    counts = dict(
        db.execute(
            select(DocumentVersion.document_id, func.count(DocumentVersion.id))
            .where(DocumentVersion.document_id.in_([d.id for d in docs]))
            .group_by(DocumentVersion.document_id)
        ).all()  # type: ignore[arg-type]
    )
    return [(d, versions.get(d.current_version_id or ""), int(counts.get(d.id, 0))) for d in docs]


def document_detail(db: Session, p: Principal, doc_id: str) -> tuple[KnowledgeDocument, list[DocumentVersion]]:
    doc = scoped.get_document(db, p, doc_id)
    versions = list(
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc.id)
            .order_by(DocumentVersion.version.desc())
        ).scalars()
    )
    if not p.is_staff:
        versions = [v for v in versions if v.id == doc.current_version_id]
    return doc, versions


def version_bytes(db: Session, p: Principal, doc_id: str, version: int) -> tuple[DocumentVersion, KnowledgeDocument]:
    doc, versions = document_detail(db, p, doc_id)
    for v in versions:
        if v.version == version:
            return v, doc
    raise scoped.NotFound("document version not found")
