"""Human claim annotations. Rows are immutable: a new label from the same annotator supersedes the old one."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, created_at_column, id_column

ANNOTATION_VERDICTS = ("supported", "contradicted", "insufficient_evidence")


class ClaimAnnotation(Base):
    __tablename__ = "claim_annotations"
    id: Mapped[str] = id_column("ann")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    claim_index: Mapped[int] = mapped_column(Integer)
    claim_sha256: Mapped[str] = mapped_column(String(64))  # binds the label to the exact claim text
    verdict: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    # Who labeled it: a staff user here, or a named external annotator in an imported file.
    annotator_key: Mapped[str] = mapped_column(String(120))
    recorded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(12))  # ui | import
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    data_class: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = created_at_column()
