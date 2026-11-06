"""Print the local demo walkthrough with the actual URLs. Credentials stay in the ignored file."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
creds_path = ROOT / ".local" / "demo-credentials.json"
if not creds_path.exists():
    raise SystemExit("No demo credentials yet. Run `make seed` first.")
creds = json.loads(creds_path.read_text())
urls = creds.get("urls", {})
print(f"Web:      {urls.get('web')}")
print(f"Sign in:  {urls.get('login')}")
print(f"API docs: {urls.get('api_docs')}")
print(f"Accounts (passwords in {creds_path.relative_to(ROOT)}):")
for email, info in creds["accounts"].items():
    print(f"  {email:28} {info['role']:9} {info.get('customer_account', info['organization'])}")
print("""
Walkthrough (see docs/demo.md):
  1. Sign in as customer@northstar.local and file an export ticket with error EXPORT_500.
  2. Sign in as support@relayops.local, open it from the Inbox, launch the Bug investigation playbook.
  3. Watch the graph and evidence; edit the draft (creates v2), then approve v2.
  4. Back in the portal, the approved reply is visible; the ticket waits on the customer.
  5. Incidents: confirm the webhook constellation (3 tickets, 2 accounts) after review.
  6. Investigations: open a finished run and start a recorded replay; nothing re-executes.
""")
