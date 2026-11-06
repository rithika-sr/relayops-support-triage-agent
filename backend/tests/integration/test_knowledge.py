from __future__ import annotations

from datetime import UTC, datetime

from relayops.services import knowledge, retrieval
from tests.factories import build_world, client_for, principal

DOC = (
    "# Exports\n\nLarge exports above 50,000 tasks should use the background export.\n\n"
    "## Errors\n\nEXPORT_500 means retry."
)


def _ingest(db, org, slug, *, visibility="public", kind="article", account=None, content=DOC, status=None, **kw):
    d, v, _ = knowledge.ingest(
        db,
        None,
        knowledge.DocumentInput(
            slug=slug,
            title=slug.replace("-", " "),
            kind=kind,
            visibility=visibility,
            content=content,
            component="exports",
            customer_account_id=account,
            **kw,
        ),
        organization_id=org,
    )
    if status:
        d.status = status
    db.commit()
    return d


def test_chunking_is_heading_aware():
    chunks = knowledge.chunk_markdown(DOC)
    assert [h for h, _ in chunks] == ["Exports", "Errors"]


def test_new_version_supersedes_previous_and_unchanged_content_is_noop(db):
    w = build_world(db)
    d1 = _ingest(db, w.org_a, "exports-guide")
    first = d1.current_version_id
    d2 = _ingest(db, w.org_a, "exports-guide")
    assert d2.current_version_id == first
    d3 = _ingest(db, w.org_a, "exports-guide", content=DOC + "\n\nNew paragraph about limits.")
    assert d3.current_version_id != first
    s = retrieval.search(db, retrieval.RetrievalScope(w.org_a, None, "staff"), "limits paragraph", mode="lexical")
    assert {h["document_version_id"] for h in s["results"]} == {d3.current_version_id}


def test_retrieval_modes_share_authorization_filters(db):
    w = build_world(db)
    _ingest(db, w.org_a, "public-a")
    _ingest(db, w.org_a, "internal-a", visibility="internal", kind="runbook")
    _ingest(db, w.org_a, "acct2-only", account=w.acct_a2)
    _ingest(db, w.org_a, "superseded-a", status="superseded")
    _ingest(
        db, w.org_a, "expired-a", valid_from=datetime(2025, 1, 1, tzinfo=UTC), valid_to=datetime(2025, 6, 1, tzinfo=UTC)
    )
    _ingest(db, w.org_b, "other-org")
    q = "background export EXPORT_500 tasks"
    cust = retrieval.RetrievalScope(w.org_a, w.acct_a1, "customer")
    staff = retrieval.RetrievalScope(w.org_a, w.acct_a1, "staff")
    for mode in ("lexical", "dense", "rrf"):
        c = {h["slug"] for h in retrieval.search(db, cust, q, mode=mode, k=20)["results"]}
        s = {h["slug"] for h in retrieval.search(db, staff, q, mode=mode, k=20)["results"]}
        assert c == {"public-a"}, mode
        assert s == {"public-a", "internal-a"}, mode


def test_customer_document_access_and_bytes_are_scoped(db):
    w = build_world(db)
    pub = _ingest(db, w.org_a, "public-a")
    internal = _ingest(db, w.org_a, "internal-a", visibility="internal", kind="runbook")
    mine = _ingest(db, w.org_a, "acct1-doc", account=w.acct_a1)
    theirs = _ingest(db, w.org_a, "acct2-doc", account=w.acct_a2)
    other_org = _ingest(db, w.org_b, "b-doc")
    c = client_for("cust1@a.test")
    listed = {d["slug"] for d in c.get("/api/knowledge").json()}
    assert listed == {"public-a", "acct1-doc"}
    assert c.get(f"/api/knowledge/{pub.id}/versions/1/raw").status_code == 200
    assert c.get(f"/api/knowledge/{mine.id}/versions/1/raw").status_code == 200
    for d in (internal, theirs, other_org):
        assert c.get(f"/api/knowledge/{d.id}").status_code == 404
        assert c.get(f"/api/knowledge/{d.id}/versions/1/raw").status_code == 404
    assert c.post("/api/knowledge/inspect", json={"query": "export"}).status_code == 403
    s = client_for("support@b.test")
    assert s.get(f"/api/knowledge/{pub.id}").status_code == 404


def test_upload_validates_type_and_creates_versions(db):
    build_world(db)
    s = client_for("support@a.test")
    form = {
        "slug": "upload-guide",
        "title": "Upload guide",
        "kind": "article",
        "visibility": "public",
        "component": "exports",
        "product_versions": "2.4, 2.5",
    }
    bad = s.post("/api/knowledge", data=form, files={"file": ("guide.pdf", b"%PDF", "application/pdf")})
    assert bad.status_code == 422
    ok = s.post("/api/knowledge", data=form, files={"file": ("guide.md", DOC.encode(), "text/markdown")})
    assert ok.status_code == 201 and ok.json()["changed"]
    assert ok.json()["document"]["product_versions"] == ["2.4", "2.5"]
    hist = s.post(
        "/api/knowledge",
        data={**form, "slug": "case-x", "kind": "historical_case"},
        files={"file": ("c.md", b"# c\n\nbody", "text/markdown")},
    )
    assert hist.status_code == 422  # historical cases must be internal
    assert (
        client_for("cust1@a.test")
        .post("/api/knowledge", data=form, files={"file": ("g.md", b"# x\n\ny", "text/markdown")})
        .status_code
        == 403
    )


def test_dense_search_ignores_vectors_from_another_embedding_model(db):
    w = build_world(db)
    _ingest(db, w.org_a, "public-a")
    from relayops.models import KnowledgeChunk

    db.query(KnowledgeChunk).update({"embedding_model": "some-other-model"})
    db.commit()
    res = retrieval.search(db, retrieval.RetrievalScope(w.org_a, None, "staff"), "export", mode="dense")
    assert res["results"] == []
    guard = retrieval.embedding_model_guard(db, w.org_a, retrieval.get_provider())
    assert guard["compatible"] is False
    assert principal(db, "support@a.test").is_staff
