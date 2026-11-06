from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from relayops.api import serializers as ser
from relayops.api.deps import DB, current_principal, staff_principal
from relayops.domain.scope import Principal, ValidationFailed
from relayops.services import knowledge as knowledge_service
from relayops.services import retrieval

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class StatusBody(BaseModel):
    status: str


class InspectBody(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    mode: Literal["lexical", "dense", "rrf"] = "rrf"
    k: int = Field(default=5, ge=1, le=20)
    customer_account_id: str | None = None
    component: str | None = None
    audience: Literal["staff", "customer"] = "staff"


@router.get("")
def list_documents(
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    p: Principal = Depends(current_principal),
    db: Session = DB,
) -> list[dict[str, Any]]:
    return [
        ser.document(d, v, n, p) for d, v, n in knowledge_service.list_documents(db, p, kind=kind, status=status, q=q)
    ]


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    slug: str = Form(...),
    title: str = Form(...),
    kind: str = Form(...),
    visibility: str = Form(...),
    component: str | None = Form(None),
    product_versions: str = Form(""),
    customer_account_id: str | None = Form(None),
    valid_from: datetime | None = Form(None),
    valid_to: datetime | None = Form(None),
    p: Principal = Depends(staff_principal),
    db: Session = DB,
) -> dict[str, Any]:
    name = (file.filename or "").lower()
    if name.endswith((".md", ".markdown")):
        media = "text/markdown"
    elif name.endswith(".txt"):
        media = "text/plain"
    else:
        raise ValidationFailed("upload a Markdown (.md) or plain text (.txt) file")
    raw = await file.read(knowledge_service.MAX_DOC_BYTES + 1)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("file must be UTF-8 text") from exc
    doc, version, changed = knowledge_service.ingest(
        db,
        p,
        knowledge_service.DocumentInput(
            slug=slug.strip(),
            title=title,
            kind=kind,
            visibility=visibility,
            content=content,
            component=component or None,
            product_versions=tuple(v.strip() for v in product_versions.split(",") if v.strip()),
            customer_account_id=customer_account_id or None,
            valid_from=valid_from,
            valid_to=valid_to,
            media_type=media,
            source_filename=file.filename,
        ),
    )
    return {"document": ser.document(doc, version, version.version, p), "changed": changed}


@router.get("/{doc_id}")
def get_document(doc_id: str, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    doc, versions = knowledge_service.document_detail(db, p, doc_id)
    current = next((v for v in versions if v.id == doc.current_version_id), None)
    return {
        "document": ser.document(doc, current, len(versions), p),
        "versions": [ser.version(v, include_content=v.id == doc.current_version_id or p.is_staff) for v in versions],
    }


@router.get("/{doc_id}/versions/{version}/raw")
def raw_version(doc_id: str, version: int, p: Principal = Depends(current_principal), db: Session = DB) -> Response:
    v, doc = knowledge_service.version_bytes(db, p, doc_id, version)
    ext = "md" if v.media_type == "text/markdown" else "txt"
    return Response(
        v.content.encode(),
        media_type=f"{v.media_type}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.slug}-v{v.version}.{ext}"',
            "X-Content-Hash": v.content_hash,
        },
    )


@router.post("/{doc_id}/status")
def set_status(
    doc_id: str, body: StatusBody, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    doc = knowledge_service.set_status(db, p, doc_id, body.status)
    return {"id": doc.id, "status": doc.status}


@router.post("/inspect")
def inspect(body: InspectBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    """Retrieval inspector: run any baseline under staff or customer-audience filters for one account."""
    if body.customer_account_id:
        from relayops.repositories import scoped

        scoped.get_account(db, p, body.customer_account_id)
    scope = retrieval.RetrievalScope(p.organization_id, body.customer_account_id, body.audience)
    return retrieval.search(db, scope, body.query, mode=body.mode, k=body.k, component=body.component)
