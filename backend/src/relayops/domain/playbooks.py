"""Typed playbook configuration. Every playbook runs on the same durable investigation graph."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from relayops.domain.routes import Route

READ_TOOLS = (
    "search_knowledge",
    "find_similar_cases",
    "search_engineering_issues",
    "get_incident_snapshot",
    "get_recent_deployments",
    "get_error_aggregates",
)

GRAPH_NODES = (
    ("load_context", "Load trusted context", "code"),
    ("extract", "Extract facts", "model"),
    ("precheck", "Trusted record lookups", "code"),
    ("investigate", "Adaptive investigation", "model+tools"),
    ("propose", "Choose route and handoff", "model"),
    ("draft_reply", "Draft customer reply (public evidence only)", "model"),
    ("verify", "Verify evidence and typed facts", "code"),
    ("review", "Human review (interrupt)", "human"),
    ("act", "Execute approved local action", "code"),
    ("audit_outcome", "Record outcome", "code"),
)


class PlaybookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str = Field(min_length=10, max_length=600)
    allowed_tools: list[str] = Field(min_length=1)
    allowed_routes: list[Route] = Field(min_length=1)
    max_turns: int = Field(ge=1, le=4)
    max_tool_calls: int = Field(ge=1, le=6)
    required_facts: list[str] = Field(default_factory=list, max_length=8)
    retrieval_mode: str = Field(default="rrf", pattern="^(lexical|dense|rrf)$")
    # agent: adaptive investigation every time. selective: typed policy first, adaptive only when ambiguous.
    execution: str = Field(default="agent", pattern="^(agent|selective)$")

    @field_validator("allowed_tools")
    @classmethod
    def _tools(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(READ_TOOLS))
        if unknown:
            raise ValueError(f"unknown tools: {', '.join(unknown)}")
        return sorted(set(v), key=READ_TOOLS.index)

    @field_validator("allowed_routes")
    @classmethod
    def _routes(cls, v: list[Route]) -> list[Route]:
        # Clarification and specialist review must always remain reachable as safe exits.
        out = list(dict.fromkeys([*v, Route.CLARIFICATION, Route.SPECIALIST_REVIEW]))
        return out


DEFAULT_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "howto": {
        "name": "How-to resolution",
        "description": "Answer a usage or policy question from current documentation, checking plan entitlements.",
        "config": {
            "focus": "Find the current documentation and policy that answer the question for this account's plan "
            "and version. Prefer current policy over historical cases. Ask for clarification if the "
            "version or plan makes the answer ambiguous.",
            "allowed_tools": ["search_knowledge", "find_similar_cases"],
            "allowed_routes": ["answer_draft", "clarification", "feature_request"],
            "max_turns": 3,
            "max_tool_calls": 4,
            "required_facts": ["product_version"],
        },
    },
    "bug": {
        "name": "Bug investigation",
        "description": "Match symptoms to known issues and diagnostics; link an existing issue or prepare a handoff.",
        "config": {
            "focus": "Identify the component, version, and error signature. Check known engineering issues for the "
            "same signature AND affected version, recent deployments, and error aggregates. Link an existing "
            "issue only when version and signature match; otherwise prepare a new engineering handoff. "
            "Timing near a deployment is correlation, not cause.",
            "allowed_tools": list(READ_TOOLS),
            "allowed_routes": ["link_existing_issue", "new_engineering_handoff", "answer_draft", "clarification"],
            "max_turns": 4,
            "max_tool_calls": 6,
            "required_facts": ["product_version", "error_code"],
        },
    },
    "feature": {
        "name": "Feature request",
        "description": "Recognize a product request, find an existing feature record, and record the request.",
        "config": {
            "focus": "Determine whether the request is already possible with current features. If not, find an "
            "existing feature request issue to link; otherwise hand off a new feature request.",
            "allowed_tools": ["search_knowledge", "search_engineering_issues", "find_similar_cases"],
            "allowed_routes": ["feature_request", "answer_draft", "new_engineering_handoff"],
            "max_turns": 3,
            "max_tool_calls": 4,
            "required_facts": [],
        },
    },
    "incident": {
        "name": "Incident triage",
        "description": "Check active incidents and diagnostic signals; propose an incident link for review.",
        "config": {
            "focus": "Check whether a reviewed incident covers this report using incident snapshots, error "
            "aggregates, and deployments. Propose linking to an existing reviewed incident only; never "
            "declare a new outage. Share only the approved public summary with the customer.",
            "allowed_tools": [
                "get_incident_snapshot",
                "get_error_aggregates",
                "get_recent_deployments",
                "search_knowledge",
            ],
            "allowed_routes": ["incident_link", "new_engineering_handoff", "clarification"],
            "max_turns": 3,
            "max_tool_calls": 5,
            "required_facts": ["first_seen"],
        },
    },
}


def choose_default_playbook(*, error_code: str | None, subject: str, body: str) -> str:
    text = f"{subject} {body}".lower()

    def has(*phrases: str) -> bool:  # whole words only: "down" must not match "downloads"
        return any(re.search(rf"\b{re.escape(w)}\b", text) for w in phrases)

    if has("feature request", "would like", "we want", "can you add", "request:"):
        return "feature"
    if has("outage", "down", "delayed", "late again", "incident"):
        return "incident"
    if error_code or has("error", "fails", "fail", "failing", "failed", "broken", "bug"):
        return "bug"
    return "howto"
