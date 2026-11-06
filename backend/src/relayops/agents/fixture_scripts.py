"""Deterministic scripted model behavior for offline CI and browser tests.

Enabled only with RELAYOPS_LLM_PROVIDER=fixture and RELAYOPS_FIXTURE_SCRIPT=generic. Runs made this way record
`model_provider=fixture`, and the UI flags them. They exercise the runtime, review, and actions; they say
nothing about model quality.
"""

from __future__ import annotations

import re
from typing import Any

_FIELD = re.compile(r"Recorded fields: component=(\S+), product_version=(\S+), error_code=(\S+),")


def _ids(user: str, pattern: str) -> list[str]:
    return re.findall(r"\[(E\d+)\][^\n]*" + pattern, user)


def generic_script(purpose: str, user: str) -> dict[str, Any]:
    if purpose == "extract":
        m = _FIELD.search(user)
        comp, ver, err = (None if v == "None" else v for v in m.groups()) if m else (None, None, None)
        subject = re.search(r"Subject: (.*)", user)
        return {
            "intent": "bug" if err else "how_to",
            "component": comp,
            "product_version": ver,
            "error_code": err,
            "first_seen": None,
            "summary": subject.group(1)[:200] if subject else "Customer report",
        }
    if purpose == "investigate":
        done = user.count("- turn ")
        if done == 0:
            return {
                "purpose": "Check known issues and current documentation for this report.",
                "action": "call_tools",
                "tool_calls": [
                    {"tool": "search_engineering_issues", "args": {"query": "error"}},
                    {"tool": "search_knowledge", "args": {"query": "export troubleshooting"}},
                ],
            }
        return {"purpose": "Evidence gathered; propose a route.", "action": "finish", "tool_calls": []}
    if purpose == "propose":
        match = re.search(r"issues matching BOTH error signature and affected version: \[?'?(E\d+)", user)
        if match:
            return {
                "route": "link_existing_issue",
                "rationale": "A known issue matches signature and version.",
                "evidence_ids": [match.group(1)],
                "issue_evidence_id": match.group(1),
                "incident_evidence_id": None,
                "missing_facts": [],
                "clarifying_questions": [],
                "observations": ["Signature and version match a tracked issue."],
                "hypotheses": [],
            }
        return {
            "route": "clarification",
            "rationale": "Not enough detail to act.",
            "evidence_ids": [],
            "issue_evidence_id": None,
            "incident_evidence_id": None,
            "missing_facts": ["steps_to_reproduce"],
            "clarifying_questions": ["Could you share the exact steps and the time it happened?"],
            "observations": [],
            "hypotheses": [],
        }
    if purpose == "draft_reply":
        pub = _ids(user, r"public")[:1]
        return {
            "reply": "Thanks for reporting this. Our team is aware of this problem. Please use Prepare in "
            "background from the Export menu as a workaround while we look into it.",
            "evidence_ids": pub,
        }
    raise ValueError(f"no fixture behavior for {purpose}")


SCRIPTS = {"generic": generic_script}
