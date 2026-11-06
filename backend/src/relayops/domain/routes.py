"""Investigation routes and the executable action each one proposes."""

from __future__ import annotations

from enum import StrEnum


class Route(StrEnum):
    ANSWER_DRAFT = "answer_draft"
    CLARIFICATION = "clarification"
    LINK_EXISTING_ISSUE = "link_existing_issue"
    NEW_ENGINEERING_HANDOFF = "new_engineering_handoff"
    FEATURE_REQUEST = "feature_request"
    INCIDENT_LINK = "incident_link"
    SPECIALIST_REVIEW = "specialist_review"


class ActionKind(StrEnum):
    POST_CUSTOMER_REPLY = "post_customer_reply"
    LINK_ENGINEERING_ISSUE = "link_engineering_issue"
    CREATE_ENGINEERING_HANDOFF = "create_engineering_handoff"
    LINK_INCIDENT = "link_incident"
    ESCALATE_SPECIALIST = "escalate_specialist"


# Every route produces a customer-facing reply draft; some also carry an internal engineering effect.
ROUTE_ACTION: dict[Route, ActionKind] = {
    Route.ANSWER_DRAFT: ActionKind.POST_CUSTOMER_REPLY,
    Route.CLARIFICATION: ActionKind.POST_CUSTOMER_REPLY,
    Route.LINK_EXISTING_ISSUE: ActionKind.LINK_ENGINEERING_ISSUE,
    Route.NEW_ENGINEERING_HANDOFF: ActionKind.CREATE_ENGINEERING_HANDOFF,
    Route.FEATURE_REQUEST: ActionKind.LINK_ENGINEERING_ISSUE,
    Route.INCIDENT_LINK: ActionKind.LINK_INCIDENT,
    Route.SPECIALIST_REVIEW: ActionKind.ESCALATE_SPECIALIST,
}

INTENTS = ("how_to", "bug", "feature_request", "incident", "account_policy", "security")
