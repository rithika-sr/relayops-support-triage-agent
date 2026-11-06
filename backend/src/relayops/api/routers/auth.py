from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from relayops.api import serializers as ser
from relayops.api.deps import (
    CSRF_COOKIE,
    DB,
    SESSION_COOKIE,
    client_ip,
    current_principal,
    require_pre_session_guard,
    safe_redirect,
)
from relayops.core.config import get_settings
from relayops.core.security import csrf_for_session
from relayops.domain.scope import Principal
from relayops.models import CustomerAccount, Organization
from relayops.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    next: str | None = Field(default=None, max_length=500)


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    organization_name: str = Field(min_length=1, max_length=200)


class AcceptInviteBody(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=256)


def _set_cookies(response: Response, token: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=s.cookie_secure, path="/"
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_for_session(token, s.session_secret),
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _me(db: Session, p: Principal) -> dict[str, Any]:
    org = db.get(Organization, p.organization_id)
    acct = db.get(CustomerAccount, p.customer_account_id) if p.customer_account_id else None
    return ser.principal(p, org.name if org else "", acct.name if acct else None)


@router.post("/login", dependencies=[Depends(require_pre_session_guard)])
def login(body: LoginBody, request: Request, response: Response, db: Session = DB) -> dict[str, Any]:
    try:
        issued = auth_service.login(
            db,
            email=body.email,
            password=body.password,
            client_ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except auth_service.Throttled as exc:
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="too many failed sign-in attempts; try again later",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except auth_service.InvalidCredentials as exc:
        db.commit()  # persist the failed attempt for throttling
        raise HTTPException(status_code=401, detail="email or password is incorrect") from exc
    _set_cookies(response, issued.token)
    return {"user": _me(db, issued.principal), "redirect_to": safe_redirect(body.next, issued.principal.role)}


@router.post("/register", dependencies=[Depends(require_pre_session_guard)])
def register(body: RegisterBody, request: Request, response: Response, db: Session = DB) -> dict[str, Any]:
    issued = auth_service.register_organization(
        db,
        name=body.name,
        email=body.email,
        password=body.password,
        organization_name=body.organization_name,
        user_agent=request.headers.get("user-agent"),
    )
    _set_cookies(response, issued.token)
    return {"user": _me(db, issued.principal), "redirect_to": "/app"}


@router.post("/accept-invitation", dependencies=[Depends(require_pre_session_guard)])
def accept_invitation(body: AcceptInviteBody, request: Request, response: Response, db: Session = DB) -> dict[str, Any]:
    issued = auth_service.accept_invitation(
        db, token=body.token, name=body.name, password=body.password, user_agent=request.headers.get("user-agent")
    )
    _set_cookies(response, issued.token)
    return {"user": _me(db, issued.principal), "redirect_to": "/portal"}


@router.post("/logout")
def logout(
    request: Request, response: Response, p: Principal = Depends(current_principal), db: Session = DB
) -> dict[str, bool]:
    auth_service.logout(db, request.cookies.get(SESSION_COOKIE, ""))
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    return _me(db, p)
