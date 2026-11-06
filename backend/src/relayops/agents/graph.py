"""The bounded investigation workflow.

load_context -> extract -> investigate (loops, one turn per step) -> propose -> draft_reply -> verify
-> review (interrupt) -> act -> audit_outcome

Code owns budgets, scope, routing constraints, verification, and writes. The model chooses which read
tools to call, proposes a route, and drafts text. Each step is checkpointed in Postgres, so a restarted
worker resumes the same thread. The review node pauses with `interrupt()`; nothing before it performs a
non-idempotent effect (the proposal insert is keyed by run and version).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from relayops.agents import prompts
from relayops.agents.llm import get_provider
from relayops.agents.outputs import Extraction, NextAction, Reply, RouteProposal
from relayops.core.clock import utcnow
from relayops.core.config import get_settings
from relayops.core.db import session_scope
from relayops.domain.incidents import normalize_signature
from relayops.domain.policies import entitlements_for
from relayops.domain.routes import ROUTE_ACTION, ActionKind, Route
from relayops.models import CustomerAccount, InvestigationRun, Ticket, TicketMessage, User
from relayops.services import actions, engineering, retrieval, review, runs
from relayops.services.tickets import ticket_target
from relayops.tools.registry import TrustedContext, dispatch, knowledge_evidence, tool_specs

MAX_CALLS_PER_TURN = 2


class RunState(TypedDict, total=False):
    run_id: str
    context: dict[str, Any]
    budgets: dict[str, Any]
    extraction: dict[str, Any]
    evidence: dict[str, dict[str, Any]]
    observations: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    turns: int
    tool_calls: int
    model_calls: int
    repairs: int
    stop_reason: str | None
    route_proposal: dict[str, Any]
    reply: dict[str, Any]
    proposal_id: str
    review: dict[str, Any]
    outcome: dict[str, Any]


def _usage(state: RunState) -> dict[str, Any]:
    return {k: state.get(k, 0) for k in ("turns", "tool_calls", "model_calls", "repairs")}


OUTPUT_TOKENS = {"extract": 300, "investigate": 300, "propose": 1100, "draft_reply": 600}


def _call_model(
    state: RunState, node: str, purpose: str, system: str, user: str, schema: dict[str, Any], model: type[BaseModel]
) -> tuple[BaseModel | None, dict[str, Any]]:
    """One structured model call with at most one repair attempt per run. Returns (validated, state delta)."""
    run_id = state["run_id"]
    delta: dict[str, Any] = {"model_calls": state.get("model_calls", 0), "repairs": state.get("repairs", 0)}
    provider = get_provider()
    s = get_settings()
    attempt_user = user
    for attempt in range(2):
        runs.check_alive(run_id)
        timeout = min(s.llm_timeout_seconds, max(1.0, runs.remaining_seconds(run_id)))
        result = provider.chat_json(
            purpose=node,
            system=system,
            user=attempt_user,
            schema=schema,
            timeout=timeout,
            max_tokens=OUTPUT_TOKENS.get(node, s.max_output_tokens),
        )
        delta["model_calls"] += 1
        error = result.parse_error
        parsed: BaseModel | None = None
        if result.parsed is not None:
            try:
                parsed = model.model_validate(result.parsed)
            except ValidationError as exc:
                error = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])
        runs.emit(
            run_id,
            "model_call",
            node,
            {
                "purpose": purpose,
                "provider": provider.name,
                "model": provider.chat_model,
                "attempt": attempt + 1,
                "duration_ms": result.duration_ms,
                "prompt_tokens": result.prompt_tokens,
                "output_tokens": result.output_tokens,
                "valid": parsed is not None,
                "error": error,
                "output": result.parsed if parsed is not None else result.content[:600],
            },
        )
        if parsed is not None:
            return parsed, delta
        if attempt == 0 and delta["repairs"] < state["budgets"]["max_repairs"]:
            delta["repairs"] += 1
            attempt_user = (
                f"{user}\n\nYour previous output was rejected: {error}. Return only valid JSON matching "
                "the schema, using only allowed values."
            )
            continue
        break
    return None, delta


def load_context(state: RunState) -> dict[str, Any]:
    run_id = state["run_id"]
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        ticket = db.get(Ticket, run.ticket_id)
        account = db.get(CustomerAccount, run.customer_account_id)
        assert ticket is not None and account is not None
        msgs = list(
            db.execute(
                select(TicketMessage).where(TicketMessage.ticket_id == ticket.id).order_by(TicketMessage.created_at)
            ).scalars()
        )
        author = db.get(User, ticket.created_by_user_id) if ticket.created_by_user_id else None
        now = utcnow()
        if run.started_at is None:
            run.started_at = now
        run.status = "running"
        as_of = run.budgets.get("as_of") or run.created_at.isoformat()
        cfg = run.budgets["playbook"]
        context = {
            "ticket": {
                "id": ticket.id,
                "number": ticket.number,
                "subject": ticket.subject,
                "component": ticket.component,
                "product_version": ticket.product_version,
                "error_code": ticket.error_code,
                "reported_severity": ticket.reported_severity,
                "restricted": ticket.restricted,
                "revision": run.ticket_revision,
                "customer_name": author.name if author else account.name,
                "messages": [
                    {
                        "author_kind": m.author_kind,
                        "visibility": m.visibility,
                        "body": m.body,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in msgs
                    if m.visibility == "customer"
                ],
                "internal_notes": [m.body for m in msgs if m.visibility == "internal"][-3:],
                "created_at": ticket.created_at.isoformat(),
            },
            "account": {
                "id": account.id,
                "name": account.name,
                "plan": account.plan,
                "product_version": account.product_version,
                "entitlements": entitlements_for(account.plan),
            },
            "target": ticket_target(ticket),
            "policy_version": run.policy_version,
            "playbook": {"key": run.playbook_key, "revision": run.playbook_revision, **cfg},
            "as_of": as_of,
            "organization_id": run.organization_id,
        }
        budgets = {k: run.budgets[k] for k in ("max_turns", "max_tool_calls", "max_repairs", "deadline_seconds")}
    runs.emit(
        run_id,
        "node_completed",
        "load_context",
        {
            "summary": f"Loaded ticket #{context['ticket']['number']} rev {context['ticket']['revision']}, "
            f"{context['account']['plan']} plan, policy {context['policy_version']}.",
            "trusted": {
                "account": context["account"]["id"],
                "plan": context["account"]["plan"],
                "due_at": context["target"]["due_at"],
                "as_of": as_of,
            },
        },
        status="running",
        current_node="extract",
    )
    return {
        "context": context,
        "budgets": budgets,
        "evidence": {},
        "observations": [],
        "decisions": [],
        "turns": 0,
        "tool_calls": 0,
        "model_calls": 0,
        "repairs": 0,
        "stop_reason": None,
    }


def extract(state: RunState) -> dict[str, Any]:
    ctx = state["context"]
    runs.emit(state["run_id"], "node_started", "extract", {})
    stop: str | None = None
    try:
        out, delta = _call_model(
            state,
            "extract",
            "Extract stated facts",
            prompts.EXTRACT_SYSTEM,
            prompts.extract_user(ctx),
            prompts.EXTRACT_SCHEMA,
            Extraction,
        )
    except runs.DeadlineExceeded:
        out, delta, stop = None, {}, "deadline_exceeded"
    t = ctx["ticket"]
    ex = (
        out.model_dump()
        if out
        else {
            "intent": "bug" if t["error_code"] else "how_to",
            "summary": t["subject"],
            "component": None,
            "product_version": None,
            "error_code": None,
            "first_seen": None,
            "customer_claims": [],
            "fallback": True,
        }
    )
    # Recorded ticket fields are trusted over model extraction; extraction only fills gaps.
    for field in ("component", "product_version", "error_code"):
        if t.get(field):
            ex[field] = t[field]
    if t["restricted"]:
        ex["intent"] = "security"
    ex["error_signature"] = normalize_signature(ex.get("error_code"))
    runs.emit(
        state["run_id"],
        "node_completed",
        "extract",
        {"summary": ex.get("summary"), "extraction": ex},
        current_node="investigate",
        usage=_usage({**state, **delta}),
    )  # type: ignore[typeddict-item]
    return {"extraction": ex, "stop_reason": stop, **delta}


def _register(evidence: dict[str, dict[str, Any]], items: list[dict[str, Any]]) -> list[str]:
    ids = []
    seen = {(e["source_type"], e["source_id"], e.get("version")): k for k, e in evidence.items()}
    for item in items:
        key = (item["source_type"], item["source_id"], item.get("version"))
        if key in seen:
            ids.append(seen[key])
            continue
        eid = f"E{len(evidence) + 1}"
        evidence[eid] = item
        seen[key] = eid
        ids.append(eid)
    return ids


def investigate(state: RunState) -> dict[str, Any]:
    run_id = state["run_id"]
    ctx = state["context"]
    b = state["budgets"]
    evidence = dict(state["evidence"])
    observations = list(state["observations"])
    decisions = list(state["decisions"])
    turns, tool_calls = state["turns"], state["tool_calls"]
    delta: dict[str, Any] = {}
    if state.get("stop_reason"):
        return {}
    if turns >= b["max_turns"] or tool_calls >= b["max_tool_calls"]:
        return {"stop_reason": "budget_exhausted"}
    runs.emit(run_id, "node_started", "investigate", {"turn": turns + 1})
    allowed = tuple(ctx["playbook"]["allowed_tools"])
    try:
        out, delta = _call_model(
            state,
            "investigate",
            f"Investigation turn {turns + 1}",
            prompts.INVESTIGATE_SYSTEM,
            prompts.investigate_user(ctx, {**state, "evidence": evidence}, tool_specs(allowed)),
            prompts.INVESTIGATE_SCHEMA,
            NextAction,
        )
    except runs.DeadlineExceeded:
        return {"stop_reason": "deadline_exceeded"}
    turns += 1
    stop: str | None = None
    if out is None:
        stop = "invalid_model_output"
    else:
        assert isinstance(out, NextAction)
        decisions.append({"turn": turns, "purpose": out.purpose, "action": out.action})
        runs.emit(
            run_id,
            "decision",
            "investigate",
            {
                "turn": turns,
                "purpose": out.purpose,
                "action": out.action,
                "requested": [c.model_dump() for c in out.tool_calls],
            },
        )
        if out.action == "finish" or not out.tool_calls:
            stop = "model_finished"
        else:
            tctx = TrustedContext(
                run_id=run_id,
                organization_id=ctx["organization_id"],
                customer_account_id=ctx["account"]["id"],
                ticket_id=ctx["ticket"]["id"],
                as_of=datetime.fromisoformat(ctx["as_of"]),
                product_version=state["extraction"].get("product_version"),
                component=state["extraction"].get("component"),
                allowed_tools=allowed,
                error_signature=state["extraction"].get("error_signature"),
                retrieval_mode=ctx["playbook"].get("retrieval_mode", "rrf"),
                result_limit=get_settings().tool_result_limit,
            )
            previous = {(o["tool"], json.dumps(o["args"], sort_keys=True)) for o in observations}
            for call in out.tool_calls[:MAX_CALLS_PER_TURN]:
                if tool_calls >= b["max_tool_calls"]:
                    stop = "budget_exhausted"
                    break
                runs.check_alive(run_id)
                tool_calls += 1
                sig = (call.tool, json.dumps(call.args, sort_keys=True))
                runs.emit(
                    run_id,
                    "tool_call",
                    "investigate",
                    {"tool": call.tool, "args": call.args, "turn": turns, "call_number": tool_calls},
                )
                if sig in previous:
                    obs_d = {
                        "tool": call.tool,
                        "status": "failed",
                        "summary": "Repeated identical call skipped.",
                        "evidence": [],
                        "data": {},
                    }
                else:
                    with session_scope() as db:
                        obs_d = dispatch(db, tctx, call.tool, call.args).as_dict()
                previous.add(sig)
                ids = _register(evidence, obs_d["evidence"])
                observations.append(
                    {
                        "turn": turns,
                        "tool": call.tool,
                        "args": call.args,
                        "status": obs_d["status"],
                        "summary": obs_d["summary"],
                        "evidence_ids": ids,
                    }
                )
                runs.emit(
                    run_id,
                    "tool_result",
                    "investigate",
                    {
                        "tool": call.tool,
                        "status": obs_d["status"],
                        "summary": obs_d["summary"],
                        "evidence_ids": ids,
                        "evidence": {i: evidence[i] for i in ids},
                        "data": obs_d.get("data", {}),
                    },
                )
    if stop is None and (turns >= b["max_turns"] or tool_calls >= b["max_tool_calls"]):
        stop = "budget_exhausted"
    new_state = {
        "evidence": evidence,
        "observations": observations,
        "decisions": decisions,
        "turns": turns,
        "tool_calls": tool_calls,
        "stop_reason": stop,
        **delta,
    }
    runs.emit(
        run_id,
        "node_completed",
        "investigate",
        {"turn": turns, "stop_reason": stop, "evidence_count": len(evidence)},
        usage=_usage({**state, **new_state}),
    )  # type: ignore[typeddict-item]
    return new_state


def after_investigate(state: RunState) -> str:
    return "propose" if state.get("stop_reason") else "investigate"


def _computed_facts(state: RunState) -> dict[str, Any]:
    ctx, ex = state["context"], state["extraction"]
    facts: dict[str, Any] = {
        "plan": ctx["account"]["plan"],
        "entitlements": ctx["account"]["entitlements"],
        "first_response_due_at": ctx["target"]["due_at"],
        "policy_version": ctx["policy_version"],
        "product_version": ex.get("product_version"),
        "error_signature": ex.get("error_signature"),
    }
    for e in state["evidence"].values():
        if e["source_type"] == "error_aggregate" and e["meta"].get("signature") == ex.get("error_signature"):
            facts["affected_accounts"] = e["meta"]["distinct_accounts"]
            facts["errors_in_window"] = e["meta"]["total_errors"]
            facts["first_seen_this_account"] = e["meta"]["this_account_first_seen"]
            facts["first_seen_any_account"] = e["meta"]["first_seen"]
    return facts


def propose(state: RunState) -> dict[str, Any]:
    run_id, ctx = state["run_id"], state["context"]
    runs.emit(run_id, "node_started", "propose", {"stop_reason": state.get("stop_reason")})
    allowed = [Route(r) for r in ctx["playbook"]["allowed_routes"]]
    rp: RouteProposal | None = None
    delta: dict[str, Any] = {}
    if state.get("stop_reason") != "deadline_exceeded":
        try:
            out, delta = _call_model(
                state,
                "propose",
                "Choose route and handoff",
                prompts.PROPOSE_SYSTEM,
                prompts.propose_user(ctx, state),
                prompts.PROPOSE_SCHEMA,
                RouteProposal,
            )
            rp = out if isinstance(out, RouteProposal) else None
        except runs.DeadlineExceeded:
            rp = None
    overrides: list[str] = []
    evidence = state["evidence"]
    verdict = "proposed"
    if rp is None:
        rp = RouteProposal(
            route=Route.SPECIALIST_REVIEW,
            rationale="No valid route proposal within budget; handing off to a human specialist.",
            evidence_ids=list(evidence)[:6],
        )
        overrides.append("model produced no valid route; human specialist handoff")
        verdict = "insufficient_evidence"
    route = rp.route
    if ctx["ticket"]["restricted"]:
        if route != Route.SPECIALIST_REVIEW:
            overrides.append(f"security-sensitive ticket: {route} -> specialist_review")
        route = Route.SPECIALIST_REVIEW
    if route not in allowed:
        overrides.append(f"route {route} not allowed by playbook -> specialist_review")
        route = Route.SPECIALIST_REVIEW
    issue_ev = evidence.get(rp.issue_evidence_id or "")
    if route == Route.LINK_EXISTING_ISSUE:
        m = (issue_ev or {}).get("meta", {}).get("match", {})
        if not issue_ev or issue_ev["source_type"] != "issue" or not (m.get("signature") and m.get("version")):
            candidates = [
                e
                for e in evidence.values()
                if e["source_type"] == "issue"
                and e["meta"]["match"].get("signature")
                and e["meta"]["match"].get("version")
            ]
            if candidates:
                issue_ev = candidates[0]
                overrides.append(f"issue link corrected to {issue_ev['meta']['key']} (signature and version match)")
            else:
                overrides.append("no issue matches both signature and affected version -> new engineering handoff")
                route = (
                    Route.NEW_ENGINEERING_HANDOFF
                    if Route.NEW_ENGINEERING_HANDOFF in allowed
                    else Route.SPECIALIST_REVIEW
                )
                issue_ev = None
    if route == Route.FEATURE_REQUEST:
        if not (issue_ev and issue_ev["source_type"] == "issue" and issue_ev.get("kind") == "feature"):
            issue_ev = next(
                (e for e in evidence.values() if e["source_type"] == "issue" and e.get("kind") == "feature"), None
            )
    incident_ev = evidence.get(rp.incident_evidence_id or "")
    if route == Route.INCIDENT_LINK and not (incident_ev and incident_ev["source_type"] == "incident"):
        incident_ev = next(
            (e for e in evidence.values() if e["source_type"] == "incident" and e["meta"]["status"] != "resolved"), None
        )
        if incident_ev is None:
            overrides.append("no reviewed incident in evidence -> clarification")
            route = Route.CLARIFICATION
    if route == Route.CLARIFICATION and not rp.clarifying_questions:
        rp.clarifying_questions = [
            f"Could you share {f.replace('_', ' ')}?"
            for f in (rp.missing_facts or ctx["playbook"].get("required_facts") or ["more detail"])
        ][:3]
        verdict = "needs_customer_information"
    action_kind = ROUTE_ACTION[route]
    if route == Route.FEATURE_REQUEST:
        action_kind = ActionKind.LINK_ENGINEERING_ISSUE if issue_ev else ActionKind.CREATE_ENGINEERING_HANDOFF
    facts = _computed_facts(state)
    with session_scope() as db:
        owner = engineering.owner_for(db, ctx["organization_id"], state["extraction"].get("component"))
    handoff = None
    if action_kind == ActionKind.CREATE_ENGINEERING_HANDOFF:
        handoff = {
            "title": rp.handoff_title or ctx["ticket"]["subject"],
            "summary": rp.handoff_summary or rp.rationale,
            "component": owner["component"],
            "team": owner["team"],
            "escalation": owner["escalation"],
            "observations": rp.observations,
            "hypotheses": rp.hypotheses,
            "reproduction": rp.reproduction,
            "impact": rp.impact,
            "missing_facts": rp.missing_facts,
            "kind": "feature" if route == Route.FEATURE_REQUEST else "bug",
        }
    internal_ids = [i for i in dict.fromkeys(rp.evidence_ids) if i in evidence]
    for ev in (issue_ev, incident_ev):
        if ev:
            internal_ids.append(next(k for k, v in evidence.items() if v is ev))
    proposal = {
        "route": route.value,
        "action_kind": action_kind.value,
        "rationale": rp.rationale,
        "overrides": overrides,
        "verdict": verdict,
        "clarifying_questions": rp.clarifying_questions,
        "missing_facts": rp.missing_facts,
        "observations": rp.observations,
        "hypotheses": rp.hypotheses,
        "handoff": handoff,
        "issue_id": issue_ev["source_id"] if issue_ev and action_kind == ActionKind.LINK_ENGINEERING_ISSUE else None,
        "issue_key": issue_ev["meta"]["key"] if issue_ev else None,
        "link_kind": "feature_request" if route == Route.FEATURE_REQUEST else "known_issue",
        "incident_id": incident_ev["source_id"] if incident_ev and route == Route.INCIDENT_LINK else None,
        "incident_public_summary": incident_ev["meta"].get("public_summary") if incident_ev else None,
        "internal_evidence_ids": list(dict.fromkeys(internal_ids)),
        "computed_facts": facts,
    }
    runs.emit(
        run_id,
        "node_completed",
        "propose",
        {"route": route.value, "action_kind": action_kind.value, "rationale": rp.rationale, "overrides": overrides},
        current_node="draft_reply",
        usage=_usage({**state, **delta}),
    )  # type: ignore[typeddict-item]
    return {"route_proposal": proposal, **delta}


SECURITY_REPLY = (
    "Thank you for reporting this. Because it may involve security, we have routed it to our security specialist "
    "team for restricted review. Please do not post passwords, tokens, or exploit details in this ticket. If you "
    "think a credential may be exposed, rotate it now. A specialist will follow up here."
)


def draft_reply(state: RunState) -> dict[str, Any]:
    run_id, ctx, rp = state["run_id"], state["context"], state["route_proposal"]
    runs.emit(run_id, "node_started", "draft_reply", {"route": rp["route"]})
    evidence = dict(state["evidence"])
    # Customer-audience evidence view: a fixed retrieval with customer visibility filters for this account,
    # run by code (not counted against the investigator's tool budget).
    if rp["route"] != Route.SPECIALIST_REVIEW:
        query = " ".join(x for x in (ctx["ticket"]["subject"], ctx["ticket"]["error_code"] or "") if x)
        with session_scope() as db:
            res = retrieval.search(
                db,
                retrieval.RetrievalScope(ctx["organization_id"], ctx["account"]["id"], "customer"),
                query,
                mode="lexical" if get_settings().llm_provider == "fixture" else "rrf",
                k=4,
                as_of=datetime.fromisoformat(ctx["as_of"]),
                kinds=("policy", "article", "release_note"),
            )
        view = [knowledge_evidence(h) for h in res["results"]]
        ids = _register(evidence, view)
        runs.emit(
            run_id,
            "tool_result",
            "draft_reply",
            {
                "tool": "customer_evidence_view",
                "status": "ok" if ids else "empty",
                "summary": f"{len(ids)} customer-visible passages (code-run retrieval, customer audience).",
                "evidence_ids": ids,
                "evidence": {i: evidence[i] for i in ids},
                "data": {"query": query},
            },
        )
    public = {
        k: v
        for k, v in evidence.items()
        if v["visibility"] == "public" and v["source_type"] in ("knowledge", "incident")
    }
    delta: dict[str, Any] = {"evidence": evidence}
    reply: dict[str, Any]
    if rp["route"] == Route.SPECIALIST_REVIEW:
        cites = [k for k, v in public.items() if v.get("meta", {}).get("slug") == "security-report-handling"]
        text = (
            SECURITY_REPLY
            if ctx["ticket"]["restricted"]
            else ("Thank you for the details. A support specialist is reviewing this ticket and will follow up here.")
        )
        reply = {"text": text, "evidence_ids": cites, "source": "template"}
    else:
        incident_summary = rp.get("incident_public_summary") if rp["route"] == Route.INCIDENT_LINK else None
        try:
            out, delta = _call_model(
                state,
                "draft_reply",
                "Draft customer reply",
                prompts.REPLY_SYSTEM,
                prompts.reply_user(ctx, rp["route"], rp["clarifying_questions"], public, incident_summary),
                prompts.REPLY_SCHEMA,
                Reply,
            )
        except runs.DeadlineExceeded:
            out = None
        if isinstance(out, Reply):
            reply = {"text": out.reply, "evidence_ids": out.evidence_ids, "source": "model"}
        else:
            qs = " ".join(rp["clarifying_questions"])
            reply = {
                "text": (
                    "Thanks for the details. "
                    + (qs or "A support specialist is reviewing this and will follow up here.")
                ).strip(),
                "evidence_ids": [],
                "source": "template",
            }
    runs.emit(
        run_id,
        "node_completed",
        "draft_reply",
        {"source": reply["source"], "chars": len(reply["text"]), "evidence_ids": reply["evidence_ids"]},
        current_node="verify",
        usage=_usage({**state, **delta}),
    )  # type: ignore[typeddict-item]
    return {**delta, "reply": reply, "evidence": evidence}


def verify(state: RunState) -> dict[str, Any]:
    run_id, ctx, rp = state["run_id"], state["context"], state["route_proposal"]
    payload = {
        "customer_reply": state["reply"]["text"],
        "reply_evidence_ids": state["reply"]["evidence_ids"],
        "reply_source": state["reply"]["source"],
        **{k: v for k, v in rp.items() if k not in ("route", "action_kind")},
        "context_snapshot": {
            "account": ctx["account"],
            "ticket": {"product_version": state["extraction"].get("product_version"), "id": ctx["ticket"]["id"]},
        },
    }
    destination: dict[str, Any] = {
        "type": "ticket_thread",
        "ticket_id": ctx["ticket"]["id"],
        "visibility": "customer",
        "adapter": "local",
    }
    if rp.get("handoff"):
        destination["engineering"] = {
            "team": rp["handoff"]["team"],
            "component": rp["handoff"]["component"],
            "adapter": "local",
        }
    if rp.get("issue_id"):
        destination["engineering_issue_id"] = rp["issue_id"]
    if rp.get("incident_id"):
        destination["incident_id"] = rp["incident_id"]
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        prop = review.create_proposal(
            db,
            run,
            route=rp["route"],
            action_kind=rp["action_kind"],
            destination=destination,
            payload=payload,
            evidence=state["evidence"],
            context=payload["context_snapshot"],
        )
        run.route = rp["route"]
        run.verdict = rp["verdict"]
        run.status = "awaiting_review"
        run.current_node = "review"
        run.usage = _usage(state)
        pid, ver = prop.id, prop.verification
    runs.emit(
        run_id,
        "proposal_created",
        "verify",
        {"proposal_id": pid, "verification": ver["status"], "failed_checks": ver["failed"]},
    )
    runs.emit(run_id, "awaiting_review", "review", {"proposal_id": pid})
    return {"proposal_id": pid}


def review_gate(state: RunState) -> dict[str, Any]:
    decision = interrupt({"proposal_id": state["proposal_id"], "reason": "human review required"})
    return {"review": decision}


def after_review(state: RunState) -> str:
    return "act" if state["review"].get("decision") == "approve" else "audit_outcome"


def act(state: RunState) -> dict[str, Any]:
    run_id, rv = state["run_id"], state["review"]
    runs.check_alive(run_id, deadline=False)  # human review time does not count against the deadline
    runs.emit(run_id, "node_started", "act", {"proposal_id": rv["proposal_id"]}, status="executing", current_node="act")
    try:
        with session_scope() as db:
            rec = actions.execute(db, rv["proposal_id"], rv["review_id"])
            outcome = {"status": rec.status, "action_id": rec.id, "receipt": rec.receipt, "kind": rec.action_kind}
    except actions.ActionRefused as exc:
        outcome = {"status": "refused", "reason": str(exc)}
    runs.emit(run_id, "action_result", "act", outcome)
    return {"outcome": outcome}


def audit_outcome(state: RunState) -> dict[str, Any]:
    run_id = state["run_id"]
    outcome = state.get("outcome") or {"status": "rejected", "proposal_id": state["review"].get("proposal_id")}
    final = (
        "rejected"
        if outcome["status"] == "rejected"
        else ("completed" if outcome["status"] in ("succeeded", "reconciled") else "failed")
    )
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        if final == "failed":
            run.error = outcome.get("reason") or outcome["status"]
    runs.emit(
        run_id,
        "run_finished",
        "audit_outcome",
        {"outcome": outcome, "usage": _usage(state)},
        status=final,
        current_node="",
    )
    return {"outcome": outcome}


def build_graph(checkpointer: Any) -> Any:
    g = StateGraph(RunState)
    for name, fn in [
        ("load_context", load_context),
        ("extract", extract),
        ("investigate", investigate),
        ("propose", propose),
        ("draft_reply", draft_reply),
        ("verify", verify),
        ("review", review_gate),
        ("act", act),
        ("audit_outcome", audit_outcome),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "extract")
    g.add_edge("extract", "investigate")
    g.add_conditional_edges("investigate", after_investigate, {"investigate": "investigate", "propose": "propose"})
    g.add_edge("propose", "draft_reply")
    g.add_edge("draft_reply", "verify")
    g.add_edge("verify", "review")
    g.add_conditional_edges("review", after_review, {"act": "act", "audit_outcome": "audit_outcome"})
    g.add_edge("act", "audit_outcome")
    g.add_edge("audit_outcome", END)
    return g.compile(checkpointer=checkpointer)
