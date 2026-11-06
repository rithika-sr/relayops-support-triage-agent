"""Build the harder synthetic slice (hard_v1).

Ten root families x three variants. Unlike the main set, tickets carry no structured component, version, or
error-code fields: facts appear only in free text (sometimes misspelled), sources conflict, errors are uncommon,
and some reports are genuinely ambiguous. Gold labels follow the documented product rules and world truth in
data/fixtures/world.json. Splits are by family (4/3/3). Author-written; no model generated, answered, or graded
these cases.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPLITS = ["dev", "dev", "dev", "dev", "validation", "validation", "validation", "test", "test", "test"]

FAMILIES = [
    ("hard_code_in_body_export", "acct_northstar", "known_issue",
     {"route": "link_existing_issue", "issues": ["ENG-101"]},
     [("Big export broken", "When I export Fleet Planning (80k tasks) to CSV the page says EXPORT_500 and nothing downloads."),
      ("Can't download our board", "Our largest board fails to export, error EXPORT_500, every time today."),
      ("CSV export error", "export of the 75k task project -> EXPORT_500. smaller ones fine")]),
    ("hard_typo_signature", "acct_northstar", "known_issue",
     {"route": "link_existing_issue", "issues": ["ENG-101"]},
     [("export 500??", "we get an 'export 500' error on the big project export"),
      ("Export_500 again", "Seeing Export-500 when exporting large projects to CSV."),
      ("export500", "large CSV exports fail with export500")]),
    ("hard_version_near_miss", "acct_orbit", "new_handoff",
     {"route": "new_engineering_handoff", "forbidden": ["link_ENG-101", "link_ENG-114"]},
     [("Exports error out", "Since the 2.5 upgrade even tiny CSV exports fail with EXPORT_500."),
      ("EXPORT_500 on small exports", "A 40-row export now returns EXPORT_500 for us."),
      ("New export failures", "Exports started failing this week with EXPORT_500, any size.")]),
    ("hard_entitlement_paraphrase", "acct_northstar", "how_to",
     {"route": "answer_draft", "evidence": ["plan-entitlements"], "forbidden": ["sso_available_business"]},
     [("Okta login", "Our IT team wants people to sign in through Okta. Is that part of our subscription?"),
      ("Company login", "Can staff log in with our company identity provider on the plan we have?"),
      ("Identity provider sign-in", "Does our subscription let us use single sign on with Azure AD?")]),
    ("hard_conflicting_history", "acct_cedar", "how_to",
     {"route": "answer_draft", "evidence": ["plan-entitlements"]},
     [("Export size", "Last year support told us we could export 50,000 rows at once. Is that still right for us?"),
      ("Row cap changed?", "We were told 50k rows per export before. What is our limit now?"),
      ("Export limit question", "How many rows can we export now? An old reply said fifty thousand.")]),
    ("hard_uncommon_error", "acct_bluefin", "new_handoff",
     {"route": "new_engineering_handoff"},
     [("Upload checksum error", "Attaching a PDF to a task fails with ATTACH_CHECKSUM_FAIL every time."),
      ("ATTACH_CHECKSUM_FAIL", "File attachments over 5 MB give ATTACH_CHECKSUM_FAIL."),
      ("Attachment verification failure", "We keep seeing ATTACH_CHECKSUM_FAIL when uploading spreadsheets.")]),
    ("hard_incident_no_code", "acct_acme", "incident",
     {"route": "incident_link", "incidents": ["inc_export_queue"]},
     [("Background export stuck", "Our background export has said 'preparing' for three hours."),
      ("Export never ready", "Prepare in background never finishes today; it was fine yesterday."),
      ("Waiting on export", "Background exports seem stuck for our whole team this morning.")]),
    ("hard_ambiguous_slow", "acct_bluefin", "clarification",
     {"route": "clarification", "missing": ["page_or_feature", "time"]},
     [("Slow", "It's slow."), ("Laggy app", "Things feel laggy for some of us."),
      ("Performance issue", "TaskFlow has been sluggish, please check.")]),
    ("hard_feature_paraphrase", "acct_orbit", "feature_request",
     {"route": "feature_request", "issues": ["ENG-110"]},
     [("Exports to our bucket", "It would be great if exports could land in our S3 bucket automatically every Monday."),
      ("Automatic exports", "Any chance of scheduling exports straight into our own storage?"),
      ("Weekly export delivery", "We'd love a weekly export pushed to our S3-compatible bucket.")]),
    ("hard_security_subtle", "acct_bluefin", "challenge_like",
     {"route": "specialist_review"},
     [("Token in a link", "A colleague's session token showed up in a URL someone sent me. I think it's exposed."),
      ("Exposed credential?", "I can see what looks like an exposed API key in a shared report link."),
      ("Possible leaked token", "There's a leaked token visible in a support screenshot we posted.")]),
]


def build() -> tuple[list[dict], dict]:
    cases = []
    for i, (fam, acct, category, gold, variants) in enumerate(FAMILIES):
        for v, (subject, body) in enumerate(variants):
            cases.append({
                "case_id": f"{fam}_v{v + 1}", "family_id": fam, "category": category, "split": SPLITS[i],
                "slice": "hard_v1", "demo": False, "as_of_offset_hours": 0, "organization_id": "org_taskflow",
                "customer_account_id": acct, "world_snapshot_id": "world_v1",
                "ticket": {"subject": subject, "body": body, "component": None, "product_version": None,
                           "error_code": None, "reported_severity": "normal"},
                "gold": {"intent": category, "component": None, "route": gold["route"],
                         "required_evidence_slugs": gold.get("evidence", []), "acceptable_issue_keys": gold.get("issues", []),
                         "acceptable_incident_ids": gold.get("incidents", []), "missing_facts": gold.get("missing", []),
                         "forbidden_claims": gold.get("forbidden", []), "incident_public": None,
                         "lenient_issue_match": False},
                "generation": {"method": "author_written_free_text", "variant": v + 1},
            })
    lines = [json.dumps(c, sort_keys=True) for c in cases]
    digest = {s: hashlib.sha256("\n".join(line for line, c in zip(lines, cases, strict=True) if c["split"] == s)
                                .encode()).hexdigest() for s in ("dev", "validation", "test")}
    manifest = {"dataset": "relayops-synthetic-hard-v1", "unit_of_split": "root family",
                "family_splits": {f[0]: SPLITS[i] for i, f in enumerate(FAMILIES)},
                "counts": {s: sum(1 for c in cases if c["split"] == s) for s in digest}, "split_sha256": digest,
                "test_split_status": "frozen; not run",
                "notes": "No structured fields; facts only in free text. Synthetic and author-written."}
    return cases, {"manifest": manifest, "lines": lines}


if __name__ == "__main__":
    cases, out = build()
    (HERE / "hard_cases.jsonl").write_text("\n".join(out["lines"]) + "\n")
    (HERE / "hard_split_manifest.json").write_text(json.dumps(out["manifest"], indent=2) + "\n")
    print(json.dumps(out["manifest"]["counts"]))
