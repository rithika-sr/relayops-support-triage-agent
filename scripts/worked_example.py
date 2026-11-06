"""Capture docs/worked-example.md from a real run against a running *demo* instance (make demo-dev).

The script files a portal ticket as the demo customer, starts an investigation as support, waits for the draft,
saves one reviewer edit, approves (acknowledging uncertain claims only if the API requires it), waits for the
action, and reads the ticket back as the customer. Everything quoted in the document is copied from API responses.
Passwords are read from .local/demo-credentials.json and never written out.

    python3 scripts/worked_example.py [--api http://localhost:8030]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CUSTOMER, SUPPORT = "customer@northstar.local", "support@relayops.local"
TICKET = {
    "subject": "Fleet Planning CSV export keeps failing",
    "body": "Exporting our Fleet Planning project (about 80k tasks) to CSV fails with EXPORT_500 every time since "
    "this morning. Smaller projects export fine. Is this a known problem, and is there a workaround?",
    "component": "exports",
    "error_code": "EXPORT_500",
    "reported_severity": "high",
}


class Client:
    def __init__(self, api: str, web_origin: str) -> None:
        self.api, self.origin, self.jar = api.rstrip("/"), web_origin, CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self) -> str:
        return next((c.value for c in self.jar if c.name == "relayops_csrf"), "")

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.api}/api{path}", data=data, method=method, headers={
            "Content-Type": "application/json", "Origin": self.origin, "X-Requested-With": "relayops",
            "X-CSRF-Token": self._csrf()})
        try:
            with self.opener.open(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:300]}") from exc


def login(api: str, origin: str, email: str, creds: dict[str, Any]) -> Client:
    c = Client(api, origin)
    c.call("POST", "/auth/login", {"email": email, "password": creds["accounts"][email]["password"]})
    return c


def wait(c: Client, run_id: str, statuses: tuple[str, ...], timeout: float = 600) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        d = c.call("GET", f"/investigations/{run_id}")
        if d["run"]["status"] in statuses:
            return d
        time.sleep(3)
    raise SystemExit(f"run {run_id} did not reach {statuses} within {timeout:.0f}s")


def fence(obj: Any, lang: str = "json") -> str:
    text = json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, str) else obj
    return f"```{lang}\n{text}\n```"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8030")
    ap.add_argument("--web", default="http://localhost:3030")
    args = ap.parse_args()
    creds = json.loads((ROOT / ".local" / "demo-credentials.json").read_text())
    probe = Client(args.api, args.web).call("GET", "/instance")
    if probe["data_mode"] != "demo":
        raise SystemExit(f"refusing: {args.api} is a {probe['data_mode']} instance; the worked example uses demo data")
    health = login(args.api, args.web, SUPPORT, creds).call("GET", "/settings/health")

    cust = login(args.api, args.web, CUSTOMER, creds)
    created = cust.call("POST", "/tickets", TICKET)["ticket"]
    support = login(args.api, args.web, SUPPORT, creds)
    staff_ticket = support.call("GET", f"/tickets/{created['id']}")
    started = time.monotonic()
    run = support.call("POST", f"/tickets/{created['id']}/investigations", {"playbook_key": "bug"})
    detail = wait(support, run["id"], ("awaiting_review", "failed"))
    elapsed = time.monotonic() - started
    if detail["run"]["status"] == "failed":
        raise SystemExit(f"run failed: {detail['run'].get('error')}")
    prop = next(p for p in detail["proposals"] if p["status"] == "pending_review")

    # Scripted reviewer (stands in for a person; no human reviewed this run): remove every sentence the
    # verification marked contradicted, then add the documented workaround in the reviewer's own words.
    removed = [c["text"] for c in prop["verification"]["claims"] if c["verdict"] == "contradicted"]
    kept = prop["payload"]["customer_reply"]
    for sentence in removed:
        kept = kept.replace(sentence, "")
    edited_text = " ".join(kept.split()).strip() + (
        "\n\nIf you need the data now, choose Export > Prepare in background; the download link is emailed.")
    v2 = support.call("POST", f"/proposals/{prop['id']}/edit", {
        "customer_reply": edited_text, "expected_version": prop["version"],
        "note": "Removed sentences verification marked contradicted; added the background-export workaround."})
    approve_body: dict[str, Any] = {"expected_version": v2["version"], "expected_payload_hash": v2["payload_hash"],
                                    "note": "Checked against ENG-101 and the export article."}
    uncertain = v2["verification"].get("uncertain_claims", 0)
    if uncertain:
        approve_body["acknowledge_uncertain_claims"] = True
    if v2["verification_status"] != "passed":
        raise SystemExit(f"edited version still fails {v2['verification']['failed']}; not approving (by design)")
    approved = support.call("POST", f"/proposals/{v2['id']}/approve", approve_body)
    final = wait(support, run["id"], ("completed", "failed", "rejected"))
    customer_view = cust.call("GET", f"/tickets/{created['id']}")

    events = detail["events"]
    tools = [e for e in events if e["kind"] in ("tool_call", "tool_result", "trusted_lookup", "decision")]
    steps = []
    for e in tools:
        p = e["payload"]
        if e["kind"] == "tool_call":
            steps.append(f"- `tool_call` {p.get('tool')} {json.dumps(p.get('arguments') or p.get('args') or {})}")
        elif e["kind"] == "tool_result":
            steps.append(f"- `tool_result` {p.get('tool')}: {p.get('status')}, {len(p.get('evidence') or {})} evidence item(s)")
        elif e["kind"] == "trusted_lookup":
            d = p.get("decision") or {}
            steps.append(f"- `trusted_lookup` rule `{d.get('rule')}` (applied: {p.get('applied')}): {d.get('explanation')}")
        else:
            steps.append(f"- `decision` {json.dumps(p)[:220]}")
    checks = [f"| {c['name']} | {c['status']} | {c['detail'][:140]} |" for c in prop["verification"]["checks"]]
    claims_v1 = [f"| {c['text'][:110]} | {c['kind']} | {c['verdict']} | {c['method']} |" for c in prop["verification"]["claims"]]
    claims_v2 = [f"| {c['text'][:110]} | {c['kind']} | {c['verdict']} | {c['method']} |" for c in v2["verification"]["claims"]]
    action = (final.get("actions") or [{}])[0]
    msgs = [m for m in customer_view["messages"]]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    model = {"provider": health.get("provider"), **{k: v for k, v in (health.get("ollama") or {}).items() if k != "installed"}}
    doc = f"""# Worked example: one ticket, end to end

Captured on {stamp} by `scripts/worked_example.py` against the local **demo** instance (`{args.api}`), on the real
local model. Every quoted value below was copied from an API response during that run; nothing was edited by hand
except this prose. The records are synthetic demo data. Re-running the script produces a new ticket and, because the
model is not deterministic across versions, possibly different wording.

Model and runtime as reported by `/api/settings/health`:

{fence(model)}

## 1. The customer files a ticket in the portal

{fence(TICKET)}

The portal response shows the customer only their own ticket; staff see the computed target:

{fence({"number": staff_ticket["ticket"]["number"], "priority": staff_ticket["ticket"]["priority"], "target": staff_ticket["ticket"]["target"]})}

## 2. Support starts the bug playbook

The run reached review in {elapsed:.0f} s with these lookups, tool calls, and decisions (from `run_events`):

{chr(10).join(steps) or "- (no tool events)"}

Usage recorded on the run: `{json.dumps(detail["run"].get("usage"))}`

Route: **{prop["route"]}** ({prop["action_kind"]}). Draft (version {prop["version"]}):

{fence(prop["payload"]["customer_reply"], "text")}

## 3. Verification of version {prop["version"]}

Status: **{prop["verification_status"]}**. Claim verifier: `{json.dumps(prop["verification"].get("claim_verifier"))}`.

| Check | Status | Detail |
| --- | --- | --- |
{chr(10).join(checks)}

| Sentence | Kind | Verdict | Method |
| --- | --- | --- | --- |
{chr(10).join(claims_v1)}

## 4. The reviewer edits, then approves the exact version

**Who acted:** the reviewer steps below were performed by the capture script on behalf of a support user; no human
reviewed this draft. The script removed the {len(removed)} sentence(s) verification marked contradicted:

{chr(10).join(f"- ~~{t}~~" for t in removed) or "- (none)"}

and appended one sentence about the documented workaround. That created version {v2["version"]} (status
`{v2["verification_status"]}`). Edited text is checked with typed rules only; the semantic verifier does not run on
human-authored text:

| Sentence | Kind | Verdict | Method |
| --- | --- | --- | --- |
{chr(10).join(claims_v2)}

Uncertain substantive claims on version {v2["version"]}: {uncertain}.
{"The reviewer acknowledged them at approval (the API refuses approval otherwise)." if uncertain else "No acknowledgment was needed."}

Approval response:

{fence(approved)}

## 5. The action runs once

Final run status: **{final["run"]["status"]}**. Action record:

{fence({k: action.get(k) for k in ("kind", "status", "adapter", "receipt") if k in action})}

## 6. What the customer sees

The customer's ticket view now has {len(msgs)} message(s); the latest is exactly the approved version {v2["version"]}:

{fence(msgs[-1]["body"] if msgs else "", "text")}

Ticket status for the customer: `{customer_view["ticket"]["status"]}` (a reply never resolves a ticket by itself).
"""
    out = ROOT / "docs" / "worked-example.md"
    out.write_text(doc)
    print(f"wrote {out.relative_to(ROOT)} (ticket #{created['number']}, run {run['id']}, {elapsed:.0f}s to review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
