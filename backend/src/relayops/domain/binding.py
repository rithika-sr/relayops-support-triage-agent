"""Approval binding: the exact facts a reviewer approved. Any change invalidates the approval."""

from __future__ import annotations

from typing import Any

from relayops.core.security import content_hash


def approval_binding(
    *,
    organization_id: str,
    customer_account_id: str,
    reviewer_user_id: str,
    ticket_id: str,
    ticket_revision: int,
    proposal_id: str,
    proposal_version: int,
    action_kind: str,
    destination: dict[str, Any],
    payload_hash: str,
    evidence_hash: str,
    policy_version: str,
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "customer_account_id": customer_account_id,
        "reviewer_user_id": reviewer_user_id,
        "ticket_id": ticket_id,
        "ticket_revision": ticket_revision,
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "action_kind": action_kind,
        "destination": destination,
        "payload_hash": payload_hash,
        "evidence_hash": evidence_hash,
        "policy_version": policy_version,
    }


def binding_hash(binding: dict[str, Any]) -> str:
    return content_hash(binding)


def binding_mismatches(approved: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Keys whose values differ, ignoring the reviewer identity (rechecked separately)."""
    keys = set(approved) | set(current)
    return sorted(k for k in keys if k != "reviewer_user_id" and approved.get(k) != current.get(k))
