"""Author-labeled calibration set for claim support (claims_v1).

Each item is one reply sentence, the cited passages it may rely on, and the author's gold verdict
(supported | contradicted | insufficient_evidence). Written by the project author against the synthetic
world; no model wrote or labeled these items. Small by design: it measures whether the verifier's
verdicts are usable, not a general accuracy figure.
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


def build() -> list[dict]:
    return [{"item_id": f"claim_{i + 1:02d}", "sentence": s, "spans": spans, "gold": gold,
             "labeled_by": "project author", "slice": "claims_v1"} for i, (s, spans, gold) in enumerate(ITEMS)]


if __name__ == "__main__":
    items = build()
    (HERE / "claims_calibration.jsonl").write_text("\n".join(json.dumps(x, sort_keys=True) for x in items) + "\n")
    print(len(items), {g: sum(1 for x in items if x["gold"] == g) for g in ("supported", "contradicted", "insufficient_evidence")})
