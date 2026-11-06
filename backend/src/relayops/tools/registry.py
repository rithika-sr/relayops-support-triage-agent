"""Typed, bounded read tools for the investigator.

Scope (organization, customer account, as-of time) comes only from `TrustedContext`, which the runtime
builds from the persisted ticket and run. Tool argument schemas forbid extra fields, so a model cannot
smuggle an organization, account, role, or destination into a call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from relayops.agents.llm import ModelUnavailable
from relayops.core.security import content_hash
from relayops.services import diagnostics, engineering, retrieval

Status = Literal["ok", "empty", "stale", "unavailable", "unauthorized", "failed"]
EXCERPT = 420


@dataclass(frozen=True)
class TrustedContext:
    run_id: str
    organization_id: str
    customer_account_id: str
    ticket_id: str
    as_of: datetime
    product_version: str | None
    component: str | None
    allowed_tools: tuple[str, ...]
    error_signature: str | None = None
    retrieval_mode: str = "rrf"
    result_limit: int = 5


@dataclass
class Evidence:
    source_type: str  # knowledge | case | issue | incident | deployment | error_aggregate
    source_id: str
    title: str
    excerpt: str
    visibility: str  # public | internal
    version: int | None = None
    content_hash: str | None = None
    kind: str | None = None
    authority: int | None = None
    timestamp: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["snapshot_hash"] = content_hash(
            {k: d[k] for k in ("source_type", "source_id", "version", "content_hash", "excerpt")}
        )
        return d


@dataclass
class Observation:
    tool: str
    status: Status
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status,
            "summary": self.summary,
            "evidence": [e.as_dict() for e in self.evidence],
            "data": self.data,
        }


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchKnowledgeArgs(_Args):
    query: str = Field(min_length=2, max_length=300)
    component: str | None = Field(default=None, max_length=32)


class FindSimilarCasesArgs(_Args):
    query: str = Field(min_length=2, max_length=300)


class SearchIssuesArgs(_Args):
    query: str = Field(min_length=2, max_length=300)
    component: str | None = Field(default=None, max_length=32)
    error_signature: str | None = Field(default=None, max_length=80)
    product_version: str | None = Field(default=None, max_length=16)


class IncidentArgs(_Args):
    component: str | None = Field(default=None, max_length=32)


class DeploymentArgs(_Args):
    component: str | None = Field(default=None, max_length=32)
    lookback_hours: int = Field(default=96, ge=1, le=168)


class ErrorArgs(_Args):
    component: str | None = Field(default=None, max_length=32)
    error_signature: str | None = Field(default=None, max_length=80)
    lookback_hours: int = Field(default=96, ge=1, le=168)


def _knowledge_item(h: dict[str, Any], source_type: str) -> Evidence:
    return Evidence(
        source_type=source_type,
        source_id=h["chunk_id"],
        title=f"{h['title']}" + (f" / {h['heading']}" if h["heading"] else ""),
        excerpt=h["text"][:EXCERPT],
        visibility=h["visibility"],
        version=h["version"],
        content_hash=h["content_hash"],
        kind=h["kind"],
        authority=h["authority"],
        timestamp=h["valid_from"],
        meta={
            "document_id": h["document_id"],
            "document_version_id": h["document_version_id"],
            "slug": h["slug"],
            "product_versions": h["product_versions"],
            "valid_to": h["valid_to"],
        },
    )


def knowledge_evidence(h: dict[str, Any]) -> dict[str, Any]:
    return _knowledge_item(h, "knowledge").as_dict()


def _knowledge(db: Session, ctx: TrustedContext, a: SearchKnowledgeArgs, *, cases: bool) -> Observation:
    tool = "find_similar_cases" if cases else "search_knowledge"
    scope = retrieval.RetrievalScope(ctx.organization_id, ctx.customer_account_id, "staff")
    kinds = ("historical_case",) if cases else ("policy", "article", "runbook", "release_note")
    note = ""
    try:
        res = retrieval.search(
            db,
            scope,
            a.query,
            mode=ctx.retrieval_mode,  # type: ignore[arg-type]
            k=ctx.result_limit,
            as_of=ctx.as_of,
            kinds=kinds,
            component=getattr(a, "component", None),
        )
    except ModelUnavailable as exc:
        res = retrieval.search(db, scope, a.query, mode="lexical", k=ctx.result_limit, as_of=ctx.as_of, kinds=kinds)
        note = f" Dense retrieval unavailable ({exc}); lexical only."
    if res.get("dense_error"):
        note = f" Dense retrieval unavailable ({res['dense_error']}); lexical only."
    hits = res["results"]
    if not hits:
        return Observation(tool, "empty", f"No authorized current documents matched.{note}")
    ev = [_knowledge_item(h, "case" if cases else "knowledge") for h in hits]
    return Observation(tool, "ok", f"{len(ev)} {'approved historical cases' if cases else 'passages'}.{note}", ev)


def search_knowledge(db: Session, ctx: TrustedContext, a: SearchKnowledgeArgs) -> Observation:
    return _knowledge(db, ctx, a, cases=False)


def find_similar_cases(db: Session, ctx: TrustedContext, a: FindSimilarCasesArgs) -> Observation:
    return _knowledge(db, ctx, SearchKnowledgeArgs(query=a.query), cases=True)


def search_engineering_issues(db: Session, ctx: TrustedContext, a: SearchIssuesArgs) -> Observation:
    rows = engineering.search_issues(
        db,
        ctx.organization_id,
        query=a.query,
        component=a.component or ctx.component,
        product_version=a.product_version or ctx.product_version,
        error_signature=a.error_signature or ctx.error_signature,
        limit=ctx.result_limit,
    )
    if not rows:
        return Observation("search_engineering_issues", "empty", "No engineering issues matched.")
    ev = [
        Evidence(
            source_type="issue",
            source_id=r["id"],
            title=f"{r['key']}: {r['title']}",
            excerpt=f"status={r['status']}; affected_versions={','.join(r['affected_versions']) or 'n/a'}; "
            f"signature={r['error_signature'] or 'n/a'}; match={r['match']}. {r['description']}"[:EXCERPT],
            visibility="internal",
            content_hash=content_hash(r),
            kind=r["kind"],
            timestamp=r["updated_at"],
            meta={
                "key": r["key"],
                "status": r["status"],
                "match": r["match"],
                "component": r["component"],
                "affected_versions": r["affected_versions"],
                "fixed_in_version": r["fixed_in_version"],
            },
        )
        for r in rows
    ]
    return Observation("search_engineering_issues", "ok", f"{len(ev)} issues.", ev)


def get_incident_snapshot(db: Session, ctx: TrustedContext, a: IncidentArgs) -> Observation:
    rows = diagnostics.incident_snapshot(db, ctx.organization_id, as_of=ctx.as_of, component=a.component)
    if not rows:
        return Observation("get_incident_snapshot", "empty", "No active or recent reviewed incidents.")
    ev = [
        Evidence(
            source_type="incident",
            source_id=r["id"],
            title=r["title"],
            excerpt=f"status={r['status']}; severity={r['severity']}; started={r['started_at']}; "
            f"public={r['public_visible']}; public_summary={r['public_summary'] or 'none'}"[:EXCERPT],
            visibility="public" if r["public_visible"] else "internal",
            content_hash=content_hash(r),
            timestamp=r["started_at"],
            meta=r,
        )
        for r in rows
    ]
    return Observation("get_incident_snapshot", "ok", f"{len(ev)} reviewed incidents.", ev)


def get_recent_deployments(db: Session, ctx: TrustedContext, a: DeploymentArgs) -> Observation:
    rows = diagnostics.recent_deployments(
        db, ctx.organization_id, as_of=ctx.as_of, component=a.component, lookback_hours=a.lookback_hours
    )
    if not rows:
        return Observation("get_recent_deployments", "empty", f"No deployments in the last {a.lookback_hours}h.")
    ev = [
        Evidence(
            source_type="deployment",
            source_id=r["id"],
            title=f"{r['component']} {r['version']} deployed",
            excerpt=f"{r['deployed_at']}: {r['summary']}",
            visibility="internal",
            content_hash=content_hash(r),
            timestamp=r["deployed_at"],
            meta=r,
        )
        for r in rows
    ]
    return Observation(
        "get_recent_deployments",
        "ok",
        f"{len(ev)} deployments. Timing alone is correlation, not a confirmed cause.",
        ev,
    )


def get_error_aggregates(db: Session, ctx: TrustedContext, a: ErrorArgs) -> Observation:
    res = diagnostics.error_summary(
        db,
        ctx.organization_id,
        as_of=ctx.as_of,
        customer_account_id=ctx.customer_account_id,
        component=a.component,
        signature=a.error_signature or ctx.error_signature,
        lookback_hours=a.lookback_hours,
    )
    if not res["series"]:
        status: Status = "stale" if res["stale"] else "empty"
        return Observation("get_error_aggregates", status, "No matching error aggregates in window.", data=res)
    ev = [
        Evidence(
            source_type="error_aggregate",
            source_id=f"agg:{s['signature']}:{s['component']}:{s['product_version']}:{res['window']['to']}",
            title=f"{s['signature']} on {s['component']} {s['product_version']}",
            excerpt=f"{s['total_errors']} errors across {s['distinct_accounts']} accounts between {s['first_seen']} "
            f"and {s['last_seen']}; this account: {s['this_account_errors']} "
            f"(first {s['this_account_first_seen'] or 'never'}).",
            visibility="internal",
            content_hash=content_hash(s),
            timestamp=s["first_seen"],
            meta=s,
        )
        for s in res["series"]
    ]
    status = "stale" if res["stale"] else "ok"
    return Observation("get_error_aggregates", status, f"{len(ev)} error series.", ev, data={"window": res["window"]})


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    fn: Callable[[Session, TrustedContext, Any], Observation]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "search_knowledge",
            "Search current policies, articles, runbooks, and release notes.",
            SearchKnowledgeArgs,
            search_knowledge,
        ),
        Tool(
            "find_similar_cases",
            "Search approved resolved historical cases (lower authority than policy).",
            FindSimilarCasesArgs,
            find_similar_cases,
        ),
        Tool(
            "search_engineering_issues",
            "Find known engineering issues with signature/version match flags.",
            SearchIssuesArgs,
            search_engineering_issues,
        ),
        Tool(
            "get_incident_snapshot",
            "List reviewed incidents active at the ticket time.",
            IncidentArgs,
            get_incident_snapshot,
        ),
        Tool(
            "get_recent_deployments", "List deployments before the ticket time.", DeploymentArgs, get_recent_deployments
        ),
        Tool(
            "get_error_aggregates",
            "Summarize hourly error counts by signature (organization-wide counts).",
            ErrorArgs,
            get_error_aggregates,
        ),
    ]
}


def tool_specs(allowed: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for name in allowed:
        t = TOOLS[name]
        schema = t.args.model_json_schema()
        out.append({"name": name, "description": t.description, "args": schema.get("properties", {})})
    return out


def dispatch(db: Session, ctx: TrustedContext, name: str, raw_args: Any) -> Observation:
    """Validate and run one tool call. Never raises for model mistakes; returns a failed observation."""
    if name not in TOOLS:
        return Observation(name, "failed", f"Unknown tool '{name}'.")
    if name not in ctx.allowed_tools:
        return Observation(name, "unauthorized", f"Tool '{name}' is not enabled for this playbook.")
    try:
        args = TOOLS[name].args.model_validate(raw_args if isinstance(raw_args, dict) else {})
    except ValidationError as exc:
        errs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
        return Observation(name, "failed", f"Invalid arguments: {errs}")
    try:
        return TOOLS[name].fn(db, ctx, args)
    except ModelUnavailable as exc:
        return Observation(name, "unavailable", str(exc))
