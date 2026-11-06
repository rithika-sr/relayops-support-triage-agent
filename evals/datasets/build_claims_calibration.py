"""Author-labeled calibration set for claim support (claims_v1).

Each item is one reply sentence, the cited passages it may rely on, and a gold verdict
(supported | contradicted | insufficient_evidence) against the synthetic world. Two splits:

- dev (claims_v1, 28 items): used while building the typed rules. Not held out.
- validation (claims_v1_val, 24 items): written before the semantic verifier was first run and never used to
  change rules or prompts.

Provenance of the labels: drafted for the maintainer with AI assistance during development and reviewed by
the maintainer as part of the commit; they are not independent human annotation and must not be reported as
human claim review. Small by design: a sanity check of whether verdicts are usable, not a general rate.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORT = "Business plans can export up to 25,000 rows per export. Larger exports use Prepare in background."
BG = "Background exports are prepared within 2 hours and a download link is emailed to the requester."
SSO = "SSO (SAML) is included only in the Enterprise plan. Business plans can use Google sign-in."
SLACK = "Slack notifications can be delayed by up to 15 minutes during high load. Email alerts are unaffected."
WEBHOOK = "Webhook signatures use HMAC-SHA256. Rotate the signing secret from Settings, then update your endpoint."

ITEMS = [
    ("Business plans can export up to 25,000 rows at a time.", {"E1": EXPORT}, "supported"),
    ("For bigger exports, use Prepare in background.", {"E1": EXPORT}, "supported"),
    ("Your plan allows exports of 50,000 rows.", {"E1": EXPORT}, "contradicted"),
    ("There is no row limit on Business exports.", {"E1": EXPORT}, "contradicted"),
    ("Exports are also available as Excel files.", {"E1": EXPORT}, "insufficient_evidence"),
    ("The download link arrives by email once the export is ready.", {"E1": BG}, "supported"),
    ("Background exports are usually ready within two hours.", {"E1": BG}, "supported"),
    ("Background exports finish within 10 minutes.", {"E1": BG}, "contradicted"),
    ("The link is posted in your Slack workspace.", {"E1": BG}, "insufficient_evidence"),
    ("SSO is only available on the Enterprise plan.", {"E1": SSO}, "supported"),
    ("Business accounts can sign in with Google.", {"E1": SSO}, "supported"),
    ("Your Business plan includes SAML single sign-on.", {"E1": SSO}, "contradicted"),
    ("Okta is supported on every plan.", {"E1": SSO}, "contradicted"),
    ("SCIM provisioning is part of Enterprise.", {"E1": SSO}, "insufficient_evidence"),
    ("Slack alerts may lag by up to fifteen minutes when load is high.", {"E1": SLACK}, "supported"),
    ("Email alerts are not affected by the Slack delay.", {"E1": SLACK}, "supported"),
    ("Email alerts are delayed as well.", {"E1": SLACK}, "contradicted"),
    ("Slack delays never exceed a minute.", {"E1": SLACK}, "contradicted"),
    ("The Slack delay was caused by a database migration.", {"E1": SLACK}, "insufficient_evidence"),
    ("Signatures are computed with HMAC-SHA256.", {"E1": WEBHOOK}, "supported"),
    ("You can rotate the signing secret in Settings.", {"E1": WEBHOOK}, "supported"),
    ("Webhook signatures use MD5.", {"E1": WEBHOOK}, "contradicted"),
    ("Old secrets keep working for 24 hours after rotation.", {"E1": WEBHOOK}, "insufficient_evidence"),
    # Valid citation, irrelevant to the claim.
    ("Webhooks retry failed deliveries five times.", {"E1": EXPORT}, "insufficient_evidence"),
    ("Your account manager will call you tomorrow.", {"E1": SLACK}, "insufficient_evidence"),
    # Two passages, one relevant.
    ("Larger exports should be prepared in the background.", {"E1": SLACK, "E2": EXPORT}, "supported"),
    ("Slack notifications are delivered instantly.", {"E1": EXPORT, "E2": SLACK}, "contradicted"),
    ("Google sign-in works on Business.", {"E1": WEBHOOK, "E2": SSO}, "supported"),
]


AUDIT = "Audit log entries are kept for 90 days on Business and 365 days on Enterprise. Admins can export them as CSV."
GUEST = "Guests can comment and view assigned tasks. Guests cannot create projects or invite other users."
API = "The REST API allows 600 requests per minute per token. Requests over the limit receive HTTP 429."
RESTORE = "Deleted projects stay in Trash for 30 days. An admin can restore them from Settings > Trash."
TZ = "Due dates are shown in each user's own time zone, set under Profile > Preferences."

VALIDATION = [
    ("Business plans keep audit log entries for 90 days.", {"E1": AUDIT}, "supported"),
    ("Admins can export the audit log as a CSV file.", {"E1": AUDIT}, "supported"),
    ("Audit logs are kept for one year on Business.", {"E1": AUDIT}, "contradicted"),
    ("Audit logs can be streamed to Splunk.", {"E1": AUDIT}, "insufficient_evidence"),
    ("Guests are able to comment on tasks.", {"E1": GUEST}, "supported"),
    ("Guests can invite other users to the workspace.", {"E1": GUEST}, "contradicted"),
    ("Guests may not create new projects.", {"E1": GUEST}, "supported"),
    ("Guests are billed at half price.", {"E1": GUEST}, "insufficient_evidence"),
    ("Each API token can make 600 requests per minute.", {"E1": API}, "supported"),
    ("Requests above the limit get an HTTP 429 response.", {"E1": API}, "supported"),
    ("The API allows 1,000 requests per minute per token.", {"E1": API}, "contradicted"),
    ("Rate limits reset at midnight UTC.", {"E1": API}, "insufficient_evidence"),
    ("Deleted projects can be restored for 30 days.", {"E1": RESTORE}, "supported"),
    ("Restoring a project is done from Settings > Trash.", {"E1": RESTORE}, "supported"),
    ("Deleted projects are removed immediately and cannot be recovered.", {"E1": RESTORE}, "contradicted"),
    ("Restored projects keep their original share links.", {"E1": RESTORE}, "insufficient_evidence"),
    ("Each user sees due dates in their own time zone.", {"E1": TZ}, "supported"),
    ("You can change your time zone under Profile > Preferences.", {"E1": TZ}, "supported"),
    ("Due dates always display in UTC.", {"E1": TZ}, "contradicted"),
    ("Workspace admins can force one time zone for everyone.", {"E1": TZ}, "insufficient_evidence"),
    ("Trash keeps deleted projects for a month.", {"E1": GUEST, "E2": RESTORE}, "supported"),
    ("The API limit is 600 requests per minute.", {"E1": TZ}, "insufficient_evidence"),
    ("Guests can view tasks assigned to them.", {"E1": API, "E2": GUEST}, "supported"),
    ("Enterprise keeps audit entries for 90 days.", {"E1": AUDIT}, "contradicted"),
]
LABELS = "maintainer-drafted with AI assistance; not independent human annotation"


def build() -> list[dict]:
    out = [{"item_id": f"claim_{i + 1:02d}", "sentence": s, "spans": spans, "gold": gold, "labeled_by": LABELS,
            "split": "dev", "slice": "claims_v1"} for i, (s, spans, gold) in enumerate(ITEMS)]
    out += [{"item_id": f"claimval_{i + 1:02d}", "sentence": s, "spans": spans, "gold": gold, "labeled_by": LABELS,
             "split": "validation", "slice": "claims_v1_val"} for i, (s, spans, gold) in enumerate(VALIDATION)]
    return out


if __name__ == "__main__":
    items = build()
    (HERE / "claims_calibration.jsonl").write_text("\n".join(json.dumps(x, sort_keys=True) for x in items) + "\n")
    for split in ("dev", "validation"):
        xs = [x for x in items if x["split"] == split]
        print(split, len(xs), {g: sum(1 for x in xs if x["gold"] == g) for g in ("supported", "contradicted", "insufficient_evidence")})
