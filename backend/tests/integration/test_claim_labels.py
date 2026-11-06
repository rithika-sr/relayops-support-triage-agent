"""Human claim labels: immutable, bound to claim text, imported with checks, and never inferred."""

from __future__ import annotations

from relayops.core.db import new_session
from relayops.models import ClaimAnnotation
from tests.agent_helpers import (
    ADMIN,
    CUSTOMER,
    SUPPORT,
    client,
    drain,
    export_bug_script,
    export_ticket,
    seeded,
    use_script,
)


def _proposal(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support, admin = client(CUSTOMER, creds), client(SUPPORT, creds), client(ADMIN, creds)
    tid = export_ticket(cust)
    run_id = support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"}).json()["id"]
    drain()
    prop = support.get(f"/api/investigations/{run_id}").json()["proposals"][0]
    return cust, support, admin, prop


def test_stats_stay_pending_without_labels_and_labels_are_bound_to_text(db, tmp_path):
    cust, support, admin, prop = _proposal(db, tmp_path)
    assert support.get("/api/annotations/stats").json()["status"] == "pending"
    claim = prop["verification"]["claims"][0]
    url = f"/api/proposals/{prop['id']}/claims/0/annotations"
    wrong = support.post(url, json={"verdict": "supported", "claim_sha256": "0" * 64})
    assert wrong.status_code == 422
    assert cust.post(url, json={"verdict": "supported", "claim_sha256": claim["sha256"]}).status_code == 403
    assert support.post(url, json={"verdict": "maybe", "claim_sha256": claim["sha256"]}).status_code == 422
    assert support.post(url, json={"verdict": "supported", "claim_sha256": claim["sha256"]}).status_code == 201
    # A later label supersedes; the earlier row is kept.
    assert support.post(url, json={"verdict": "contradicted", "claim_sha256": claim["sha256"]}).status_code == 201
    with new_session() as s:
        assert s.query(ClaimAnnotation).count() == 2
    listed = support.get(f"/api/proposals/{prop['id']}/annotations").json()
    assert listed[0]["consensus"] == "contradicted" and len(listed[0]["labels"]) == 1
    st = support.get("/api/annotations/stats").json()
    assert st["status"] == "measured" and st["annotated_claims"] == 1
    assert sum(sum(v.values()) for v in st["by_method"].values()) == 1


def test_import_dry_run_duplicates_and_disagreement(db, tmp_path):
    _, support, admin, prop = _proposal(db, tmp_path)
    claim = prop["verification"]["claims"][0]
    item = {"proposal_id": prop["id"], "claim_index": 0, "claim_sha256": claim["sha256"], "verdict": "supported"}
    body = {"annotator_label": "rater-1", "items": [item], "dry_run": True}
    assert support.post("/api/annotations/import", json=body).status_code == 403
    dry = admin.post("/api/annotations/import", json=body).json()
    assert dry["dry_run"] and dry["created"] == 1 and not dry["committed"]
    with new_session() as s:
        assert s.query(ClaimAnnotation).count() == 0
    bad = admin.post(
        "/api/annotations/import", json={**body, "dry_run": False, "items": [item, {**item, "claim_sha256": "f" * 64}]}
    ).json()
    assert not bad["committed"] and bad["errors"][0]["row"] == 1
    with new_session() as s:
        assert s.query(ClaimAnnotation).count() == 0  # all-or-nothing
    ok = admin.post("/api/annotations/import", json={**body, "dry_run": False}).json()
    again = admin.post("/api/annotations/import", json={**body, "dry_run": False}).json()
    assert ok["created"] == 1 and again["created"] == 0 and again["duplicates"] == 1
    other = {**body, "annotator_label": "rater-2", "dry_run": False, "items": [{**item, "verdict": "contradicted"}]}
    assert admin.post("/api/annotations/import", json=other).json()["created"] == 1
    listed = support.get(f"/api/proposals/{prop['id']}/annotations").json()
    assert listed[0]["consensus"] == "disagreement"
    st = support.get("/api/annotations/stats").json()
    assert st["annotator_disagreements"] == 1 and st["by_method"] == {}
    exported = support.get("/api/annotations/export").json()
    assert {x["annotator"] for x in exported["items"]} == {"import:rater-1", "import:rater-2"}
