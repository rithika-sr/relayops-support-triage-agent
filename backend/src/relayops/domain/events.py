"""Event schema v1. Every event name has a fixed, typed property set; unknown names or fields are rejected.

Customer-initiated events count as account activity for retention. Free text is limited to the help search
query (truncated) so that zero-result searches can surface knowledge gaps.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1
OPTIONAL = object()

# name -> {property: (type, required)}
SCHEMA: dict[str, dict[str, tuple[type, bool]]] = {
    "user.signed_in": {},
    "ticket.created": {"ticket_id": (str, True), "source_kind": (str, True)},
    "reply.published": {"ticket_id": (str, True), "action_id": (str, True)},
    "help.searched": {"query": (str, True), "results": (int, True)},
    "article.viewed": {"document_id": (str, True)},
    "article.feedback": {"document_id": (str, True), "helpful": (bool, True)},
    "help.escalated": {"ticket_id": (str, True), "document_id": (str, False), "query": (str, False)},
    "experiment.exposed": {"experiment": (str, True), "variant": (str, True)},
}
CUSTOMER_ACTIVITY = (
    "user.signed_in",
    "ticket.created",
    "help.searched",
    "article.viewed",
    "article.feedback",
    "help.escalated",
)
MAX_TEXT = 120


class EventInvalid(ValueError):
    pass


def validate(name: str, props: dict[str, Any], version: int = SCHEMA_VERSION) -> dict[str, Any]:
    if version != SCHEMA_VERSION:
        raise EventInvalid(f"unsupported schema version {version}; this server accepts {SCHEMA_VERSION}")
    spec = SCHEMA.get(name)
    if spec is None:
        raise EventInvalid(f"unknown event name {name!r}")
    extra = set(props) - set(spec)
    if extra:
        raise EventInvalid(f"{name}: unknown properties {sorted(extra)}")
    clean: dict[str, Any] = {}
    for key, (typ, required) in spec.items():
        if key not in props or props[key] is None:
            if required:
                raise EventInvalid(f"{name}: missing {key}")
            continue
        value = props[key]
        if typ is int and isinstance(value, bool) or not isinstance(value, typ):
            raise EventInvalid(f"{name}: {key} must be {typ.__name__}")
        clean[key] = value[:MAX_TEXT] if isinstance(value, str) else value
    return clean
