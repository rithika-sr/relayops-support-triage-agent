from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Computed, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column

EMBED_DIM = 768


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)
    id: Mapped[str] = id_column("doc")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    # Null means organization-wide; set means only that customer account (and staff) may see it.
    customer_account_id: Mapped[str | None] = mapped_column(ForeignKey("customer_accounts.id"))
    slug: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32))  # policy | article | historical_case | runbook | release_note
    visibility: Mapped[str] = mapped_column(String(16))  # public | internal
    component: Mapped[str | None] = mapped_column(String(64))
    product_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="current")  # current | superseded | retired
    current_version_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)
    id: Mapped[str] = id_column("dv")
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(64), default="text/markdown")
    source_filename: Mapped[str | None] = mapped_column(String(255))
    valid_from: Mapped[datetime | None] = mapped_column(Tz)
    valid_to: Mapped[datetime | None] = mapped_column(Tz)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),)
    id: Mapped[str] = id_column("chk")
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(heading, '') || ' ' || text)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at_column()
