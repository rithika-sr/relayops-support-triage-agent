"""Deterministically expand the structured synthetic world into knowledge articles and historical tickets.

Outputs are committed so seeding does not depend on running this script:
  data/knowledge/taskflow/generated/*.md
  data/fixtures/historical_tickets.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DOCS = ROOT / "data" / "knowledge" / "taskflow" / "generated"
OUT_TICKETS = ROOT / "data" / "fixtures" / "historical_tickets.json"

ACCOUNTS = ["acct_northstar", "acct_acme", "acct_bluefin", "acct_cedar", "acct_orbit"]
VERSION = {"acct_northstar": "2.4", "acct_acme": "2.5", "acct_bluefin": "2.4", "acct_cedar": "2.3", "acct_orbit": "2.5"}

# component -> list of (topic, customer question, answer steps, settings path)
HOWTO = {
    "projects": [
        ("Archiving and restoring projects", "How do I restore an archived project?",
         "Open Projects, choose the Archived filter, open the project menu, and select Restore. Restored projects keep their tasks, comments, and permissions.", "Projects > Archived"),
        ("Moving tasks between projects", "Can I move tasks to another project?",
         "Select tasks, choose Move, and pick the destination project. Custom fields that do not exist in the destination are kept as read-only history.", "Task menu > Move"),
        ("Project templates", "How do I create a project from a template?",
         "Choose New project, then From template. Workspace admins manage templates under Settings, then Templates.", "Settings > Templates"),
    ],
    "billing": [
        ("Changing plans", "How do I upgrade or downgrade our plan?",
         "Owners open Settings, then Billing, then Change plan. Upgrades apply immediately with a prorated charge; downgrades apply at the next renewal.", "Settings > Billing"),
        ("Invoices and receipts", "Where can I download invoices?",
         "Settings, then Billing, then Invoices lists all invoices as PDF. Billing contacts receive each invoice by email.", "Settings > Billing > Invoices"),
        ("Adding seats", "How are added seats billed?",
         "Seats added mid-term are prorated to the renewal date and appear on the next invoice as a separate line.", "Settings > Billing > Seats"),
    ],
    "notifications": [
        ("Muting project notifications", "How do I stop notifications for one project?",
         "Open the project, choose the bell icon, and select Muted. Mentions still notify you unless you also disable mention alerts.", "Project > Notifications"),
        ("Digest schedule", "Can I change when the daily digest arrives?",
         "Digests send at 08:00 local time. Users can switch to a weekly digest under Profile, then Notifications.", "Profile > Notifications"),
    ],
    "api": [
        ("Creating API tokens", "How do I create an API token?",
         "Open Profile, then API tokens, then Create token. Tokens inherit your permissions and can be revoked at any time.", "Profile > API tokens"),
        ("Pagination", "How does pagination work on the tasks endpoint?",
         "From 2.4 the tasks endpoint uses a cursor. Pass the next_cursor value from the previous response until it is null.", "API reference"),
    ],
    "integrations": [
        ("Connecting Slack", "How do I connect Slack to a project?",
         "Settings, then Integrations, then Slack, then Connect. Choose the channel per project. Reconnect if Slack shows the app as disconnected.", "Settings > Integrations > Slack"),
        ("Calendar sync", "Can due dates sync to Google Calendar?",
         "Enable Calendar sync under Profile, then Integrations. Only tasks assigned to you are synced.", "Profile > Integrations"),
    ],
    "exports": [
        ("Background exports", "Where do background exports appear?",
         "Completed background exports appear under Settings, then Exports, for 7 days. Owners and admins can see all exports for the workspace.", "Settings > Exports"),
    ],
    "sso": [
        ("Enforcing SSO", "How do I require SSO for all members?",
         "On Enterprise, after a successful test login, enable Enforce SSO under Settings, then Security. Keep one owner account with password access for recovery.", "Settings > Security"),
    ],
    "webhooks": [
        ("Webhook delivery log", "How can I see why a webhook delivery failed?",
         "Settings, then Webhooks, then Delivery log shows each attempt with the response code and timing for 7 days.", "Settings > Webhooks > Delivery log"),
    ],
}

# Historical case families: (component, subject template, body, error, resolution, route, issue_key, intent)
FAMILIES = [
    ("exports", "CSV export fails on large project", "Export of a project with about {n}k tasks returns EXPORT_500.", "EXPORT_500",
     "Known issue ENG-101 on 2.4. Customer used Prepare in background; export succeeded. Ticket linked to ENG-101.",
     "link_existing_issue", "ENG-101", "bug"),
    ("exports", "XLSX export missing custom fields", "Custom fields are not in the XLSX file.", None,
     "On 2.3 this was ENG-102, fixed in 2.4. Customer upgraded and confirmed columns present.", "link_existing_issue",
     "ENG-102", "bug"),
    ("exports", "Export hits row limit", "Export stops with EXPORT_LIMIT.", "EXPORT_LIMIT",
     "Explained the plan row limit and recommended filtering or background export.", "answer_draft", None, "how_to"),
    ("sso", "SAML login rejected", "Users see SAML_CLOCK_SKEW when signing in.", "SAML_CLOCK_SKEW",
     "Identity provider clock was 4 minutes fast. Customer fixed NTP; logins succeeded.", "answer_draft", None, "how_to"),
    ("webhooks", "Webhook retries stop early", "Deliveries stop retrying after 3 attempts.", "WEBHOOK_RETRY_EXHAUSTED",
     "Matches ENG-104 on 2.5. Linked ticket; advised replaying from the delivery log.", "link_existing_issue", "ENG-104",
     "bug"),
    ("webhooks", "How to verify webhook signatures", "What is the signature algorithm?", None,
     "Shared the webhooks setup article: HMAC-SHA256 over raw body with endpoint secret.", "answer_draft", None, "how_to"),
    ("notifications", "Digest email late", "Digest arrived hours late.", "NOTIFY_QUEUE_LAG",
     "Linked to the notifications incident and ENG-105; shared the public status summary.", "incident_link", "ENG-105",
     "incident"),
    ("api", "429 without Retry-After", "Rate limited responses lack headers.", "API_429_NO_HEADERS",
     "Matches ENG-106. Advised exponential backoff starting at 1 second until fixed.", "link_existing_issue", "ENG-106",
     "bug"),
    ("api", "API rate limit question", "What is the API limit per minute?", None,
     "600 requests per minute per token; shared the rate limits article.", "answer_draft", None, "how_to"),
    ("billing", "Proration credit shown twice", "Invoice preview shows the same credit twice.", None,
     "Display issue ENG-107, fixed in 2.4.2; final invoices were correct.", "link_existing_issue", "ENG-107", "bug"),
    ("projects", "Archived project appears in search", "Archived projects show up in global search.",
     "SEARCH_ARCHIVED_VISIBLE", "Matches ENG-108 on 2.5; linked.", "link_existing_issue", "ENG-108", "bug"),
    ("integrations", "Slack disconnects daily", "Slack integration shows 401 and disconnects.", "SLACK_TOKEN_REFRESH_401",
     "Matches ENG-109; reconnect as a workaround.", "link_existing_issue", "ENG-109", "bug"),
    ("exports", "Request: scheduled exports to S3", "We want exports pushed to our S3 bucket weekly.", None,
     "Recorded as a vote on feature ENG-110.", "feature_request", "ENG-110", "feature_request"),
    ("webhooks", "Request: per-project webhook secrets", "Can each project have its own secret?", None,
     "Recorded as a vote on feature ENG-111.", "feature_request", "ENG-111", "feature_request"),
    ("projects", "Request: Gantt baseline", "We need to compare plans against a baseline.", None,
     "Recorded as a vote on feature ENG-112.", "feature_request", "ENG-112", "feature_request"),
    ("billing", "How to add seats", "How are new seats billed mid-term?", None,
     "Explained proration to renewal date.", "answer_draft", None, "how_to"),
    ("projects", "Restore archived project", "Accidentally archived a project.", None,
     "Explained restore from the Archived filter.", "answer_draft", None, "how_to"),
    ("sso", "Possible token exposure in shared screenshot", "A screenshot with an API token was posted publicly.", None,
     "Routed to restricted security review; customer rotated the token.", "specialist_review", None, "security"),
]


def write_docs() -> int:
    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    for old in OUT_DOCS.glob("*.md"):
        old.unlink()
    n = 0
    for component, items in HOWTO.items():
        for title, question, answer, path in items:
            slug = "howto-" + title.lower().replace(" ", "-").replace("&", "and")
            (OUT_DOCS / f"{slug}.md").write_text(
                f"---\nslug: {slug}\ntitle: {title}\nkind: article\nvisibility: public\ncomponent: {component}\n"
                f"product_versions: 2.4, 2.5\nvalid_from: 2026-06-01T00:00:00Z\n---\n"
                f"# {title}\n\n## Question\n\n{question}\n\n## Answer\n\n{answer}\n\n## Where\n\n{path}\n"
            )
            n += 1
    return n


def write_history() -> int:
    rng = random.Random(7375)
    tickets = []
    case_docs = 0
    for i in range(126):
        fam = FAMILIES[i % len(FAMILIES)]
        component, subject, body, err, resolution, route, issue, intent = fam
        acct = ACCOUNTS[rng.randrange(len(ACCOUNTS))]
        version = VERSION[acct]
        if issue in ("ENG-102",):
            version = "2.3"
        if issue in ("ENG-104", "ENG-105", "ENG-108"):
            version = "2.5"
        offset = -rng.randint(200, 4000)
        tickets.append({
            "external_event_id": f"hist-{i:03d}",
            "family_id": f"hist_{component}_{i % len(FAMILIES):02d}",
            "account": acct,
            "offset_hours": offset,
            "subject": subject,
            "body": body.format(n=rng.choice([55, 60, 72, 90])),
            "component": component,
            "product_version": version,
            "error_code": err,
            "resolution_summary": resolution,
            "route": route,
            "linked_issue": issue,
            "intent": intent,
            "reported_severity": rng.choice(["low", "normal", "normal", "high"]),
        })
    # The obsolete-policy trap: a real 2025 case that is no longer correct.
    tickets.append({
        "external_event_id": "hist-sso-2025",
        "family_id": "hist_sso_business_2025",
        "account": "acct_northstar",
        "offset_hours": -9000,
        "subject": "Enable SSO on Business plan",
        "body": "Can we turn on SAML SSO? We are on Business.",
        "component": "sso",
        "product_version": "2.3",
        "error_code": None,
        "resolution_summary": "Business plan includes SSO (2025 policy). Customer enabled it under Settings > Security.",
        "route": "answer_draft",
        "linked_issue": None,
        "intent": "account_policy",
        "reported_severity": "normal",
    })
    for t in tickets:
        t["case_document"] = t["external_event_id"] in {f"hist-{i:03d}" for i in range(18)} or t[
            "external_event_id"] == "hist-sso-2025"
        case_docs += int(t["case_document"])
    OUT_TICKETS.write_text(json.dumps({"_note": "Synthetic resolved historical tickets.", "tickets": tickets}, indent=1))
    return len(tickets), case_docs  # type: ignore[return-value]


if __name__ == "__main__":
    docs = write_docs()
    count, cases = write_history()  # type: ignore[misc]
    print(f"generated {docs} articles, {count} historical tickets ({cases} approved case documents)")
