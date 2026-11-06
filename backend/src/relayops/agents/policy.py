"""Typed decision policy for the selective execution path.

Before any model-driven investigation, code runs a few trusted lookups scoped by the ticket's organization,
account, and as-of time: known issues for the reported signature and version, reviewed incidents for the
reported signature, this account's error aggregates, and typed plan entitlements. When those facts decide the
route under documented support rules, the selective path uses that route directly; otherwise it falls back to
the adaptive investigator. The model still writes the customer reply.

Customer-entered component, version, and error code are *reported* facts. A decision records whether the
signature was corroborated by this account's own error aggregates.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from relayops.domain.incidents import normalize_signature
from relayops.services import diagnostics, engineering

# Questions about a typed entitlement: (entitlement key, pattern).
ENTITLEMENT_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    ("sso", re.compile(r"\b(sso|single sign-?on|saml)\b", re.I)),
    ("scim", re.compile(r"\bscim\b", re.I)),
    ("webhooks", re.compile(r"\bwebhooks?\b.{0,40}\b(available|included|plan|use)\b", re.I)),
    (
        "export_row_limit",
        re.compile(r"\b(row limit|rows? (per|can) .{0,20}export|export .{0,30}(limit|cap|rows))", re.I),
    ),
]
QUESTION = re.compile(r"\?|\b(can we|can i|do we|does our|is .{0,30}included|how many)\b", re.I)


@dataclass
class TrustedFacts:
    signature: str | None
    signature_basis: str  # reported | corroborated | absent
    version: str | None
    matching_issues: list[dict[str, Any]] = field(default_factory=list)
    near_miss_issues: list[dict[str, Any]] = field(default_factory=list)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    entitlement_topic: str | None = None
    entitlement_value: Any = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyDecision:
    route: str | None  # None means not decisive: use adaptive investigation
    rule: str
    explanation: str
    issue: dict[str, Any] | None = None
    incident: dict[str, Any] | None = None

    @property
    def decisive(self) -> bool:
        return self.route is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def gather(
    db: Session,
    *,
    organization_id: str,
    customer_account_id: str,
    as_of: datetime,
    component: str | None,
    version: str | None,
    error_code: str | None,
    text: str,
    entitlements: dict[str, Any],
) -> TrustedFacts:
    sig = normalize_signature(error_code)
    facts = TrustedFacts(signature=sig, signature_basis="absent" if not sig else "reported", version=version)
    if sig:
        issues = engineering.search_issues(
            db, organization_id, query=sig, component=component, product_version=version, error_signature=sig, limit=10
        )
        facts.matching_issues = [i for i in issues if i["match"]["signature"] and i["match"]["version"]]
        facts.near_miss_issues = [i for i in issues if i["match"]["signature"] and not i["match"]["version"]]
        facts.incidents = [
            i
            for i in diagnostics.incident_snapshot(db, organization_id, as_of=as_of, component=None, signature=sig)
            if i["status"] != "resolved"
        ]
        agg = diagnostics.error_summary(
            db,
            organization_id,
            as_of=as_of,
            customer_account_id=customer_account_id,
            component=None,
            signature=sig,
            lookback_hours=168,
        )
        if any(s["this_account_errors"] > 0 for s in agg["series"]):
            facts.signature_basis = "corroborated"
    if QUESTION.search(text):
        for key, rx in ENTITLEMENT_TOPICS:
            if rx.search(text) and key in entitlements:
                facts.entitlement_topic, facts.entitlement_value = key, entitlements[key]
                break
    return facts


def decide(facts: TrustedFacts, *, restricted: bool, allowed_routes: list[str]) -> PolicyDecision:
    """Ordered, documented rules. Each returns a route only when the records settle it."""

    def allowed(route: str) -> bool:
        return route in allowed_routes

    if restricted:
        return PolicyDecision(
            "specialist_review", "restricted", "Security-sensitive report: restricted specialist review."
        )
    if facts.incidents and allowed("incident_link"):
        inc = facts.incidents[0]
        return PolicyDecision(
            "incident_link",
            "reviewed_incident_signature",
            f"A reviewed incident ({inc['title']}) has the same error signature.",
            incident=inc,
        )
    if len(facts.matching_issues) == 1 and allowed("link_existing_issue"):
        issue = facts.matching_issues[0]
        return PolicyDecision(
            "link_existing_issue",
            "known_issue_signature_version",
            f"{issue['key']} matches the {facts.signature_basis} error signature and affected version {facts.version}.",
            issue=issue,
        )
    if facts.signature and not facts.matching_issues and not facts.incidents and allowed("new_engineering_handoff"):
        near = ", ".join(i["key"] for i in facts.near_miss_issues)
        return PolicyDecision(
            "new_engineering_handoff",
            "new_signature",
            f"No known issue or reviewed incident matches {facts.signature} on version "
            f"{facts.version}"
            + (f" (same signature on other versions: {near}; not linked)" if near else "")
            + ". The cause is not known.",
        )
    if facts.entitlement_topic and allowed("answer_draft"):
        return PolicyDecision(
            "answer_draft",
            "typed_entitlement",
            f"The current plan entitlement for {facts.entitlement_topic} answers this "
            f"(value: {facts.entitlement_value}).",
        )
    return PolicyDecision(None, "ambiguous", "Records do not settle the route; adaptive investigation is needed.")
