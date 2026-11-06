from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from relayops.agents.llm import OllamaProvider, get_provider
from relayops.api.deps import DB, admin_principal, current_principal, staff_principal
from relayops.api.serializers import iso
from relayops.core.config import get_settings
from relayops.domain import policies
from relayops.domain.scope import Principal
from relayops.models import ApiToken, CustomerAccount, Invitation, Membership, User
from relayops.services import auth as auth_service
from relayops.services import retrieval

router = APIRouter(prefix="/settings", tags=["settings"])


class InvitationBody(BaseModel):
    email: str = Field(max_length=320)
    customer_account_id: str


class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = ["mcp:read"]


@router.get("/health")
def health(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    s = get_settings()
    out: dict[str, Any] = {"database": "ok"}
    try:
        db.execute(text("select 1"))
        out["pgvector"] = db.execute(text("select extversion from pg_extension where extname='vector'")).scalar()
    except Exception as exc:  # pragma: no cover - surfaced to operators
        out["database"] = f"error: {exc.__class__.__name__}"
    provider = get_provider()
    out["provider"] = provider.name
    if isinstance(provider, OllamaProvider):
        out["ollama"] = provider.health()
    else:
        out["ollama"] = {"reachable": False, "note": "fixture provider configured: no live inference"}
    out["embedding_index"] = retrieval.embedding_model_guard(db, p.organization_id, provider)
    out["embedding_dim"] = s.embed_dim
    out["budgets"] = {
        "max_turns": s.max_investigation_turns,
        "max_tool_calls": s.max_tool_calls,
        "max_repairs": s.max_repair_attempts,
        "deadline_seconds": s.run_deadline_seconds,
        "num_ctx": s.num_ctx,
        "max_output_tokens": s.max_output_tokens,
    }
    return out


@router.get("/policy")
def policy(p: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {
        "policy_version": policies.POLICY_VERSION,
        "basis": "24/7 elapsed hours (no business-hours calendar)",
        "first_response_hours": policies.FIRST_RESPONSE_HOURS,
        "entitlements": policies.ENTITLEMENTS,
    }


@router.get("/connectors")
def connectors(p: Principal = Depends(staff_principal)) -> dict[str, Any]:
    return {
        "action_mode": get_settings().action_mode,
        "adapters": [
            {
                "name": "local",
                "enabled": True,
                "description": "Approved replies become customer-visible messages in this app; handoffs create local "
                "engineering records. No email is sent.",
            },
            {
                "name": "github_issues",
                "enabled": False,
                "description": "Not connected. A deterministic simulated adapter exists only for failure-mode tests.",
            },
            {"name": "email", "enabled": False, "description": "Not implemented. RelayOps does not send email."},
        ],
    }


@router.get("/members")
def members(p: Principal = Depends(admin_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Membership, User, CustomerAccount)
        .join(User, User.id == Membership.user_id)
        .outerjoin(CustomerAccount, CustomerAccount.id == Membership.customer_account_id)
        .where(Membership.organization_id == p.organization_id)
        .order_by(Membership.role, User.email)
    ).all()
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "name": u.name,
            "role": m.role,
            "customer_account": a.name if a else None,
            "since": iso(m.created_at),
        }
        for m, u, a in rows
    ]


@router.get("/invitations")
def invitations(p: Principal = Depends(admin_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Invitation).where(Invitation.organization_id == p.organization_id).order_by(Invitation.created_at.desc())
    ).scalars()
    return [
        {
            "id": i.id,
            "email": i.email,
            "customer_account_id": i.customer_account_id,
            "expires_at": iso(i.expires_at),
            "accepted_at": iso(i.accepted_at),
        }
        for i in rows
    ]


@router.post("/invitations", status_code=201)
def create_invitation(
    body: InvitationBody, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    inv, token = auth_service.create_invitation(db, p, email=body.email, customer_account_id=body.customer_account_id)
    s = get_settings()
    return {
        "id": inv.id,
        "email": inv.email,
        "token": token,
        "expires_at": iso(inv.expires_at),
        "accept_url": f"{s.web_origin}/register?invite={token}",
        "note": "Shown once. RelayOps does not email invitations; share this link yourself.",
    }


@router.get("/tokens")
def tokens(p: Principal = Depends(admin_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ApiToken).where(ApiToken.organization_id == p.organization_id).order_by(ApiToken.created_at.desc())
    ).scalars()
    return [
        {
            "id": t.id,
            "name": t.name,
            "scopes": t.scopes,
            "created_at": iso(t.created_at),
            "revoked_at": iso(t.revoked_at),
            "last_used_at": iso(t.last_used_at),
        }
        for t in rows
    ]


@router.post("/tokens", status_code=201)
def create_token(body: TokenBody, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    row, token = auth_service.create_api_token(db, p, name=body.name, scopes=body.scopes)
    return {
        "id": row.id,
        "name": row.name,
        "scopes": row.scopes,
        "token": token,
        "note": "Shown once. Read-only MCP scope; it cannot call REST mutation endpoints.",
    }


@router.post("/tokens/{token_id}/revoke")
def revoke_token(token_id: str, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, bool]:
    auth_service.revoke_api_token(db, p, token_id)
    return {"ok": True}
