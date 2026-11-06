"""The three compared systems. All read the same authorized world through the same services.

rules   keyword classification + deterministic routing + lexical retrieval (no model)
rag     one fixed retrieval stage (knowledge RRF top-5, issue search on the ticket's signature/version,
        incident snapshot for the component, trusted account facts) and one structured model call
agent   the product runtime: bounded adaptive tool use, proposal, verification (paused at review)
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select

from relayops.agents import prompts
from relayops.agents.llm import get_provider
from relayops.core.db import session_scope
from relayops.domain.policies import entitlements_for, is_security_sensitive
from relayops.models import CustomerAccount, InvestigationRun, Proposal
from relayops.services import diagnostics, engineering, retrieval, runs
from relayops.workers import worker

QUESTION = re.compile(r"\?|^(how|can|what|where|is|are|does|do|which|why)\b", re.I | re.M)
FEATURE = re.compile(r"\b(would like|feature request|can you add|we want|please add|request:)\b", re.I)


def _knowledge(db: Any, org: str, acct: str, query: str, mode: str, as_of: datetime, k: int = 5) -> list[dict]:
    scope = retrieval.RetrievalScope(org, acct, "staff")
    res = retrieval.search(db, scope, query, mode=mode, k=k, as_of=as_of,  # type: ignore[arg-type]
                           kinds=("policy", "article", "runbook", "release_note"))
    return res["results"]


def rules_system(case: dict, ticket_id: str, as_of: datetime) -> dict[str, Any]:
    t = case["ticket"]
    org, acct = case["organization_id"], case["customer_account_id"]
    text = f"{t['subject']} {t['body']}"
    started = time.monotonic()
    with session_scope() as db:
        hits = _knowledge(db, org, acct, text, "lexical", as_of)
        issues = engineering.search_issues(db, org, query=text, component=t["component"],
                                           product_version=t["product_version"], error_signature=t["error_code"])
        incidents = diagnostics.incident_snapshot(db, org, as_of=as_of, component=t["component"])
    full = [i for i in issues if i["match"]["signature"] and i["match"]["version"]]
    inc = [i for i in incidents if t["error_code"] and i["error_signature"] == t["error_code"]]
    if is_security_sensitive(text):
        route = "specialist_review"
    elif FEATURE.search(text):
        route = "feature_request"
    elif t["error_code"] and inc:
        route = "incident_link"
    elif t["error_code"] and full:
        route = "link_existing_issue"
    elif t["error_code"]:
        route = "new_engineering_handoff"
    elif QUESTION.search(text) and len(t["body"]) > 30:
        route = "answer_draft"
    else:
        route = "clarification"
    issue_key = full[0]["key"] if route == "link_existing_issue" and full else None
    if route == "feature_request":
        feats = [i for i in issues if i["kind"] == "feature"]
        issue_key = feats[0]["key"] if feats else None
    reply = hits[0]["text"][:600] if route == "answer_draft" and hits else "Thanks, support will follow up."
    return {"route": route, "reply": reply, "issue_key": issue_key,
            "incident_id": inc[0]["id"] if route == "incident_link" else None,
            "evidence_slugs": [h["slug"] for h in hits], "cited_ok": None, "model_calls": 0, "tool_calls": 0,
            "tool_path": ["lexical_retrieval", "issue_search", "incident_snapshot"], "verification": None,
            "latency_ms": int((time.monotonic() - started) * 1000)}


RAG_SCHEMA = {
    "type": "object",
    "properties": {
        "route": prompts.PROPOSE_SCHEMA["properties"]["route"],
        "issue_evidence_id": {"type": ["string", "null"], "maxLength": 8},
        "incident_evidence_id": {"type": ["string", "null"], "maxLength": 8},
        "reply": {"type": "string", "maxLength": 1400},
        "evidence_ids": {"type": "array", "items": {"type": "string", "maxLength": 8}, "maxItems": 6},
    },
    "required": ["route", "reply", "evidence_ids"],
}


def rag_system(case: dict, ticket_id: str, as_of: datetime) -> dict[str, Any]:
    t = case["ticket"]
    org, acct = case["organization_id"], case["customer_account_id"]
    text = f"{t['subject']} {t['body']}"
    started = time.monotonic()
    with session_scope() as db:
        account = db.get(CustomerAccount, acct)
        assert account is not None
        hits = _knowledge(db, org, acct, text, "rrf", as_of)
        issues = engineering.search_issues(db, org, query=text, component=t["component"],
                                           product_version=t["product_version"] or account.product_version,
                                           error_signature=t["error_code"], limit=3)
        incidents = diagnostics.incident_snapshot(db, org, as_of=as_of, component=t["component"])
    evidence: dict[str, dict] = {}
    for h in hits:
        evidence[f"E{len(evidence) + 1}"] = {"kind": h["kind"], "visibility": h["visibility"], "title": h["title"],
                                              "text": h["text"][:420], "slug": h["slug"]}
    for i in issues:
        evidence[f"E{len(evidence) + 1}"] = {"kind": "issue", "visibility": "internal", "title": f"{i['key']} {i['title']}",
                                              "text": f"status {i['status']} versions {i['affected_versions']} match {i['match']}",
                                              "key": i["key"]}
    for i in incidents:
        evidence[f"E{len(evidence) + 1}"] = {"kind": "incident", "visibility": "public" if i["public_visible"] else "internal",
                                              "title": i["title"], "text": f"{i['status']} {i['public_summary'] or ''}",
                                              "incident_id": i["id"]}
    block = "\n".join(f"[{k}] ({v['kind']}, {v['visibility']}) {v['title']}: {v['text']}" for k, v in evidence.items())
    user = (f"Allowed routes: answer_draft, clarification, link_existing_issue, new_engineering_handoff, "
            f"feature_request, incident_link, specialist_review.\nTrusted account facts: plan={account.plan}, "
            f"version={account.product_version}, entitlements={entitlements_for(account.plan)}\n"
            f"<customer_data>\nSubject: {t['subject']}\n{t['body']}\nRecorded: component={t['component']}, "
            f"version={t['product_version']}, error_code={t['error_code']}\n</customer_data>\n<evidence>\n{block}\n"
            "</evidence>\nChoose the route and write the customer reply from public evidence only. Return JSON.")
    provider = get_provider()
    res = provider.chat_json(purpose="rag_single_pass", system=prompts.PROPOSE_SYSTEM, user=user, schema=RAG_SCHEMA,
                             timeout=90, max_tokens=900)
    out = res.parsed or {}
    route = out.get("route") if isinstance(out.get("route"), str) else None
    if is_security_sensitive(text):
        route = "specialist_review"
    issue = evidence.get(out.get("issue_evidence_id") or "", {})
    inc = evidence.get(out.get("incident_evidence_id") or "", {})
    cited = [c for c in out.get("evidence_ids", []) if isinstance(c, str)]
    cited_ok = sum(1 for c in cited if c in evidence and evidence[c]["visibility"] == "public")
    return {"route": route, "reply": out.get("reply", ""), "issue_key": issue.get("key"),
            "incident_id": inc.get("incident_id"), "evidence_slugs": [h["slug"] for h in hits],
            "cited_ok": (cited_ok, len(cited)), "model_calls": 1, "tool_calls": 0,
            "tool_path": ["fixed_retrieval", "single_generation"], "verification": None,
            "parse_error": res.parse_error, "latency_ms": int((time.monotonic() - started) * 1000)}


def agent_system(case: dict, ticket_id: str, as_of: datetime, principal: Any, execution: str = "agent") -> dict[str, Any]:
    """execution='agent' is the adaptive investigator; 'selective' is the hybrid policy-first path."""
    started = time.monotonic()
    with session_scope() as db:
        run = runs.start_run(db, principal, ticket_id, as_of=as_of, execution=execution)
        run_id = run.id
    while worker.process_one("eval-worker"):
        pass
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        prop = db.execute(select(Proposal).where(Proposal.run_id == run_id).order_by(Proposal.version.desc())).scalars().first()
        from relayops.models import RunEvent

        events = list(db.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).scalars())
    slugs: list[str] = []
    path: list[str] = []
    for e in events:
        if e.kind == "tool_call":
            path.append(e.payload["tool"])
        if e.kind == "tool_result":
            slugs += [v["meta"]["slug"] for v in e.payload.get("evidence", {}).values() if v.get("meta", {}).get("slug")]
    out: dict[str, Any] = {"route": run.route, "status_run": run.status, "run_id": run_id, "tool_path": path,
                           "evidence_slugs": list(dict.fromkeys(slugs)), "model_calls": run.usage.get("model_calls"),
                           "tool_calls": run.usage.get("tool_calls"), "latency_ms": int((time.monotonic() - started) * 1000),
                           "error": run.error}
    if prop is not None:
        ver = prop.verification
        prov = next((c for c in ver["checks"] if c["name"] == "provenance"), None)
        cited = prop.payload.get("reply_evidence_ids") or []
        out |= {"reply": prop.payload.get("customer_reply", ""), "issue_key": prop.payload.get("issue_key")
                if prop.action_kind == "link_engineering_issue" else None,
                "incident_id": prop.payload.get("incident_id"), "verification": ver["status"],
                "handoff": prop.payload.get("handoff"), "questions": prop.payload.get("clarifying_questions") or [],
                "claims": ver.get("claims", []),
                "failed_checks": ver["failed"],
                "cited_ok": (len(cited) if prov and prov["status"] == "pass" else 0, len(cited))}
    return out
