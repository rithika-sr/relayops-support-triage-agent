"""Validated model outputs. Schema validity is checked here; domain correctness is checked in verification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from relayops.domain.policies import COMPONENTS
from relayops.domain.routes import INTENTS, Route


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Extraction(_Out):
    intent: str
    component: str | None = None
    product_version: str | None = Field(default=None, max_length=16)
    error_code: str | None = Field(default=None, max_length=80)
    first_seen: str | None = Field(default=None, max_length=80)
    summary: str = Field(max_length=600)
    customer_claims: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("intent")
    @classmethod
    def _intent(cls, v: str) -> str:
        if v not in INTENTS:
            raise ValueError(f"intent must be one of {INTENTS}")
        return v

    @field_validator("component")
    @classmethod
    def _component(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower().strip()
        return v if v in COMPONENTS else None


class ToolCall(_Out):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class NextAction(_Out):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=3, max_length=300)
    action: str
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=3)

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in ("call_tools", "finish"):
            raise ValueError("action must be call_tools or finish")
        return v


class RouteProposal(_Out):
    route: Route
    rationale: str = Field(max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    issue_evidence_id: str | None = None
    incident_evidence_id: str | None = None
    missing_facts: list[str] = Field(default_factory=list, max_length=8)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=5)
    observations: list[str] = Field(default_factory=list, max_length=10)
    hypotheses: list[str] = Field(default_factory=list, max_length=6)
    handoff_title: str | None = Field(default=None, max_length=200)
    handoff_summary: str | None = Field(default=None, max_length=1500)
    reproduction: str | None = Field(default=None, max_length=1000)
    impact: str | None = Field(default=None, max_length=600)


class Reply(_Out):
    reply: str = Field(min_length=10, max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
