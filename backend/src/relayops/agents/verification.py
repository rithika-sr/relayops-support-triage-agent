"""Deterministic verification of a proposal against records.

Structural checks (schema, provenance, visibility, currency) and typed fact checks (entitlements, issue
version match, incident visibility, internal identifiers) are computed from records. Lexical overlap is
reported as such: it is not semantic proof that a cited source supports a claim.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.domain.routes import ActionKind
from relayops.models import ComponentOwner, CustomerAccount, EngineeringIssue, Incident, KnowledgeDocument

_ROOT_CAUSE = re.compile(
    r"\b(root cause (is|was)|was caused by|is caused by|caused by the (deploy|deployment|release|update)|"
    r"because of the (deploy|deployment|release|update))\b",
    re.I,
)
_CONFIRMED_OUTAGE = re.compile(r"\b(confirmed|ongoing|major|platform[- ]wide) (outage|incident)\b", re.I)
_SSO_AVAILABLE = re.compile(
    r"\b(sso|single sign-on|saml)\b[^.]{0,80}\b(is included|are included|included in your|is available|"
    r"can (enable|turn on|set up)|you can enable)\b",
    re.I,
)
_NEGATION = re.compile(
    r"\b(not|isn't|aren't|no longer|only (in|on|for) (the )?enterprise|requires? (an )?enterprise)\b", re.I
)
_ISSUE_KEY = re.compile(r"\b[A-Z]{2,5}-\d{1,5}\b")
_WORD = re.compile(r"[a-z0-9_]{3,}")
_STOP = {
    "the",
    "and",
    "for",
    "you",
    "your",
    "this",
    "that",
    "with",
    "are",
    "can",
    "our",
    "from",
    "have",
    "will",
    "please",
    "thanks",
    "thank",
    "team",
    "we",
    "let",
    "know",
    "any",
    "has",
    "not",
}


def _check(name: str, ok: bool | None, detail: str, method: str) -> dict[str, Any]:
    status = "warn" if ok is None else ("pass" if ok else "fail")
    return {"name": name, "status": status, "detail": detail, "method": method}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 12]


def _overlap(sentence: str, sources: list[str]) -> float:
    words = {w for w in _WORD.findall(sentence.lower()) if w not in _STOP}
    if not words:
        return 1.0
    pool = set()
    for s in sources:
        pool |= set(_WORD.findall(s.lower()))
    return len(words & pool) / len(words)


def verify(
    db: Session,
    *,
    organization_id: str,
    customer_account_id: str,
    action_kind: str,
    payload: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    reply = (payload.get("customer_reply") or "").strip()
    cited = list(dict.fromkeys(payload.get("reply_evidence_ids") or []))
    internal_cited = list(dict.fromkeys(payload.get("internal_evidence_ids") or []))

    # 1. Schema / required fields for the action.
    missing = []
    if not reply:
        missing.append("customer_reply")
    if action_kind == ActionKind.CREATE_ENGINEERING_HANDOFF:
        h = payload.get("handoff") or {}
        missing += [f"handoff.{k}" for k in ("title", "summary", "component") if not h.get(k)]
    if action_kind == ActionKind.LINK_ENGINEERING_ISSUE and not payload.get("issue_id"):
        missing.append("issue_id")
    if action_kind == ActionKind.LINK_INCIDENT and not payload.get("incident_id"):
        missing.append("incident_id")
    checks.append(
        _check("required_fields", not missing, "missing: " + ", ".join(missing) if missing else "complete", "schema")
    )

    # 2. Provenance: every cited id was retrieved in this run.
    unknown = [c for c in cited + internal_cited if c not in evidence]
    checks.append(
        _check(
            "provenance",
            not unknown,
            f"unknown evidence ids: {unknown}" if unknown else f"{len(cited)} reply citations exist",
            "provenance",
        )
    )

    # 3. Visibility: the customer reply may cite only public evidence.
    private = [c for c in cited if c in evidence and evidence[c]["visibility"] != "public"]
    checks.append(
        _check(
            "reply_visibility",
            not private,
            f"reply cites internal evidence {private}" if private else "reply cites public evidence only",
            "visibility",
        )
    )

    # 4. Currency: cited documents are still the current version and not superseded.
    stale = []
    for c in cited + internal_cited:
        e = evidence.get(c)
        if not e or e["source_type"] not in ("knowledge", "case"):
            continue
        doc = db.get(KnowledgeDocument, e["meta"]["document_id"])
        if (
            doc is None
            or doc.organization_id != organization_id
            or doc.status != "current"
            or (doc.current_version_id != e["meta"]["document_version_id"])
        ):
            stale.append(c)
    checks.append(
        _check(
            "source_currency",
            not stale,
            f"superseded or changed sources: {stale}" if stale else "all cited sources current",
            "policy",
        )
    )

    # 5. Internal identifiers and other customers must not leak into the reply.
    leaks: list[str] = []
    keys = set(
        db.execute(select(EngineeringIssue.key).where(EngineeringIssue.organization_id == organization_id)).scalars()
    )
    leaks += sorted({k for k in _ISSUE_KEY.findall(reply) if k in keys})
    teams = set(
        db.execute(select(ComponentOwner.team).where(ComponentOwner.organization_id == organization_id)).scalars()
    )
    leaks += sorted(t for t in teams if t and t in reply.lower())
    others = db.execute(
        select(CustomerAccount.name).where(
            CustomerAccount.organization_id == organization_id, CustomerAccount.id != customer_account_id
        )
    ).scalars()
    leaks += sorted(n for n in others if n.lower() in reply.lower())
    checks.append(
        _check(
            "no_internal_disclosure",
            not leaks,
            f"reply mentions internal or other-customer identifiers: {leaks}" if leaks else "none found",
            "policy",
        )
    )

    # 6. Entitlement facts computed from the account's plan.
    ent = context["account"]["entitlements"]
    sso_claims = [s for s in _sentences(reply) if _SSO_AVAILABLE.search(s) and not _NEGATION.search(s)]
    checks.append(
        _check(
            "entitlement_sso",
            not (sso_claims and not ent.get("sso")),
            f"reply says SSO is available but plan '{context['account']['plan']}' is not entitled"
            if sso_claims and not ent.get("sso")
            else f"consistent with plan entitlements (sso={ent.get('sso')})",
            "policy",
        )
    )

    # 7. Unsupported causal or outage claims.
    has_confirmed_incident = any(
        e["source_type"] == "incident" and e["meta"].get("status") in ("investigating", "monitoring", "resolved")
        for e in evidence.values()
    )
    handoff = payload.get("handoff") or {}
    causal = [
        s for s in _sentences(reply + "\n" + "\n".join(handoff.get("observations") or [])) if _ROOT_CAUSE.search(s)
    ]
    checks.append(
        _check(
            "no_unsupported_root_cause",
            not causal,
            f"states a cause as fact: {causal[:2]}" if causal else "no causal claims stated as fact",
            "policy",
        )
    )
    outage = [s for s in _sentences(reply) if _CONFIRMED_OUTAGE.search(s)]
    checks.append(
        _check(
            "no_unconfirmed_outage",
            not (outage and not has_confirmed_incident),
            f"outage claim without reviewed incident: {outage[:1]}" if outage and not has_confirmed_incident else "ok",
            "policy",
        )
    )

    # 8. Typed issue and incident checks.
    if payload.get("issue_id"):
        issue = db.get(EngineeringIssue, payload["issue_id"])
        version = context["ticket"].get("product_version")
        if issue is None or issue.organization_id != organization_id:
            checks.append(_check("issue_link", False, "issue not found in this organization", "record"))
        elif payload.get("link_kind") == "feature_request":
            checks.append(_check("issue_link", issue.kind == "feature", f"{issue.key} kind={issue.kind}", "record"))
        else:
            ok = bool(version and version in (issue.affected_versions or []))
            checks.append(
                _check(
                    "issue_link",
                    ok,
                    f"{issue.key} affected_versions={issue.affected_versions}, ticket version={version}",
                    "record",
                )
            )
    if payload.get("incident_id"):
        inc = db.get(Incident, payload["incident_id"])
        ok_inc = inc is not None and inc.organization_id == organization_id
        checks.append(
            _check("incident_link", ok_inc, "reviewed incident exists" if ok_inc else "incident not found", "record")
        )
        if ok_inc and inc is not None and not inc.public_visible and inc.title.lower() in reply.lower():
            checks.append(_check("incident_visibility", False, "reply names an internal-only incident", "visibility"))

    # 9. Claim support: lexical overlap only; never presented as entailment.
    sources = [evidence[c]["excerpt"] for c in cited if c in evidence]
    sources.append(" ".join(str(v) for v in context["account"]["entitlements"].values()))
    sources.append(context["account"]["plan"])
    claims = []
    for s in _sentences(reply):
        ov = _overlap(s, sources) if sources else 0.0
        claims.append(
            {
                "text": s,
                "lexical_overlap": round(ov, 2),
                "label": "provenance_checked" if cited and ov >= 0.35 else "semantically_unverified",
            }
        )
    unverified = sum(1 for c in claims if c["label"] == "semantically_unverified")
    checks.append(
        _check(
            "claim_support_lexical",
            None if unverified else True,
            f"{unverified}/{len(claims)} sentences have low lexical overlap with cited sources "
            "(lexical overlap is not semantic proof)",
            "lexical",
        )
    )

    failed = [c["name"] for c in checks if c["status"] == "fail"]
    return {
        "status": "failed" if failed else "passed",
        "failed": failed,
        "checks": checks,
        "claims": claims,
        "note": "Automated checks cover provenance, visibility, currency, and typed facts. Semantic support of "
        "claims is not verified automatically; human review is required.",
    }
