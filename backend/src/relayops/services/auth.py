"""Registration, login, session resolution, logout, and invitations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.core.config import get_settings
from relayops.core.security import hash_password, new_token, token_digest, verify_password
from relayops.domain.scope import Conflict, NotFound, Principal, ValidationFailed
from relayops.models import (
    ApiToken,
    AuthSession,
    CustomerAccount,
    Invitation,
    LoginAttempt,
    Membership,
    Organization,
    User,
)
from relayops.repositories.scoped import require_admin
from relayops.services import audit

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 12


class InvalidCredentials(Exception):
    pass


class Throttled(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("too many failed attempts")
        self.retry_after = retry_after


@dataclass(frozen=True)
class IssuedSession:
    token: str
    principal: Principal
    expires_at_iso: str


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 320:
        raise ValidationFailed("enter a valid email address")
    return email


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValidationFailed(f"password must be at least {MIN_PASSWORD} characters")
    if len(password) > 256:
        raise ValidationFailed("password is too long")


def _principal(user: User, m: Membership, via: str = "session", scopes: frozenset[str] = frozenset()) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        name=user.name,
        membership_id=m.id,
        organization_id=m.organization_id,
        role=m.role,
        customer_account_id=m.customer_account_id,
        via=via,
        scopes=scopes,
    )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "org"


def _issue_session(db: Session, user: User, m: Membership, user_agent: str | None) -> IssuedSession:
    s = get_settings()
    token = new_token()
    expires = utcnow() + timedelta(hours=s.session_ttl_hours)
    db.add(
        AuthSession(
            user_id=user.id,
            membership_id=m.id,
            token_hash=token_digest(token),
            expires_at=expires,
            user_agent=(user_agent or "")[:300],
        )
    )
    return IssuedSession(token=token, principal=_principal(user, m), expires_at_iso=expires.isoformat())


def register_organization(
    db: Session, *, name: str, email: str, password: str, organization_name: str, user_agent: str | None = None
) -> IssuedSession:
    """Self-service registration always creates a *new* organization owned by the registrant.

    It never accepts a role or an existing organization ID, so it cannot grant staff access elsewhere.
    """
    email = normalize_email(email)
    validate_password(password)
    if not name.strip() or not organization_name.strip():
        raise ValidationFailed("name and organization name are required")
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflict("an account with this email already exists")
    base = _slugify(organization_name)
    slug, n = base, 1
    while db.execute(select(Organization.id).where(Organization.slug == slug)).first():
        n += 1
        slug = f"{base}-{n}"
    org = Organization(name=organization_name.strip()[:200], slug=slug, data_class=get_settings().data_mode)
    user = User(email=email, name=name.strip()[:200], password_hash=hash_password(password))
    db.add_all([org, user])
    db.flush()
    m = Membership(user_id=user.id, organization_id=org.id, role="admin")
    db.add(m)
    from relayops.services import playbooks as playbook_service  # a new organization can investigate right away

    playbook_service.ensure_default_playbooks(db, org.id)
    try:
        db.flush()
    except IntegrityError as exc:
        raise Conflict("an account with this email already exists") from exc
    audit.record(
        db,
        organization_id=org.id,
        action="org.registered",
        target_type="organization",
        target_id=org.id,
        actor_kind="user",
        detail={"owner_email": email},
    )
    return _issue_session(db, user, m, user_agent)


def accept_invitation(
    db: Session, *, token: str, name: str, password: str, user_agent: str | None = None
) -> IssuedSession:
    """Invitations are customer-account scoped. The role is always `customer`."""
    validate_password(password)
    inv = db.execute(
        select(Invitation).where(Invitation.token_hash == token_digest(token)).with_for_update()
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.expires_at < utcnow():
        raise ValidationFailed("this invitation is invalid or has expired")
    if db.execute(select(User).where(User.email == inv.email)).scalar_one_or_none():
        raise Conflict("an account with this email already exists; sign in instead")
    user = User(email=inv.email, name=name.strip()[:200] or inv.email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    m = Membership(
        user_id=user.id,
        organization_id=inv.organization_id,
        role="customer",
        customer_account_id=inv.customer_account_id,
    )
    db.add(m)
    inv.accepted_at = utcnow()
    db.flush()
    audit.record(
        db,
        organization_id=inv.organization_id,
        action="invitation.accepted",
        target_type="invitation",
        target_id=inv.id,
        actor_kind="user",
        detail={"email": inv.email},
    )
    return _issue_session(db, user, m, user_agent)


def _check_throttle(db: Session, email: str, client_ip: str) -> None:
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.login_window_minutes)
    recent = select(func.count(LoginAttempt.id)).where(
        LoginAttempt.created_at >= since, LoginAttempt.success.is_(False)
    )
    by_email = db.execute(recent.where(LoginAttempt.email == email)).scalar_one()
    by_ip = db.execute(recent.where(LoginAttempt.client_ip == client_ip)).scalar_one()
    # Per-account limit stops guessing one password; a looser per-IP limit stops spraying.
    if by_email >= s.login_max_failures or by_ip >= s.login_max_failures * 4:
        raise Throttled(retry_after=s.login_window_minutes * 60)


def login(db: Session, *, email: str, password: str, client_ip: str, user_agent: str | None = None) -> IssuedSession:
    try:
        email = normalize_email(email)
    except ValidationFailed as exc:
        raise InvalidCredentials() from exc
    _check_throttle(db, email, client_ip)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        db.add(LoginAttempt(email=email, client_ip=client_ip, success=False))
        raise InvalidCredentials()
    m = (
        db.execute(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
        .scalars()
        .first()
    )
    if m is None:
        db.add(LoginAttempt(email=email, client_ip=client_ip, success=False))
        raise InvalidCredentials()
    db.add(LoginAttempt(email=email, client_ip=client_ip, success=True))
    audit.record(
        db,
        organization_id=m.organization_id,
        action="auth.login",
        target_type="user",
        target_id=user.id,
        actor_kind="user",
    )
    issued = _issue_session(db, user, m, user_agent)
    if m.role == "customer":
        from relayops.services import events

        events.record(
            db,
            organization_id=m.organization_id,
            name="user.signed_in",
            properties={},
            customer_account_id=m.customer_account_id,
            actor_user_id=user.id,
        )
    return issued


def resolve_session(db: Session, token: str) -> tuple[Principal, AuthSession] | None:
    if not token:
        return None
    row = db.execute(
        select(AuthSession, User, Membership)
        .join(User, User.id == AuthSession.user_id)
        .join(Membership, Membership.id == AuthSession.membership_id)
        .where(AuthSession.token_hash == token_digest(token))
    ).first()
    if row is None:
        return None
    sess, user, m = row
    now = utcnow()
    if sess.revoked_at is not None or sess.expires_at <= now or not user.is_active:
        return None
    if sess.last_seen_at is None or (now - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = now
    return _principal(user, m), sess


def logout(db: Session, token: str) -> bool:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == token_digest(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def revoke_all_sessions(db: Session, user_id: str) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def create_invitation(db: Session, p: Principal, *, email: str, customer_account_id: str) -> tuple[Invitation, str]:
    require_admin(p)
    email = normalize_email(email)
    acct = db.execute(
        select(CustomerAccount).where(
            CustomerAccount.id == customer_account_id, CustomerAccount.organization_id == p.organization_id
        )
    ).scalar_one_or_none()
    if acct is None:
        raise NotFound("customer account not found")
    token = new_token()
    inv = Invitation(
        organization_id=p.organization_id,
        customer_account_id=acct.id,
        email=email,
        token_hash=token_digest(token),
        created_by_user_id=p.user_id,
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(inv)
    db.flush()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="invitation.created",
        target_type="invitation",
        target_id=inv.id,
        detail={"email": email, "account": acct.id},
    )
    return inv, token


MCP_SCOPES = frozenset({"mcp:read"})


def create_api_token(db: Session, p: Principal, *, name: str, scopes: list[str]) -> tuple[ApiToken, str]:
    require_admin(p)
    if not scopes or not set(scopes) <= MCP_SCOPES:
        raise ValidationFailed("only the mcp:read scope is supported")
    token = "rlo_" + new_token()
    row = ApiToken(
        organization_id=p.organization_id,
        membership_id=p.membership_id,
        name=name.strip()[:120] or "token",
        token_hash=token_digest(token),
        scopes=sorted(set(scopes)),
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="api_token.created",
        target_type="api_token",
        target_id=row.id,
        detail={"scopes": row.scopes},
    )
    return row, token


def revoke_api_token(db: Session, p: Principal, token_id: str) -> None:
    require_admin(p)
    row = db.execute(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.organization_id == p.organization_id)
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("token not found")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        audit.record(
            db,
            organization_id=p.organization_id,
            actor=p,
            action="api_token.revoked",
            target_type="api_token",
            target_id=row.id,
        )


def resolve_api_token(db: Session, token: str) -> Principal | None:
    row = db.execute(
        select(ApiToken, Membership, User)
        .join(Membership, Membership.id == ApiToken.membership_id)
        .join(User, User.id == Membership.user_id)
        .where(ApiToken.token_hash == token_digest(token))
    ).first()
    if row is None:
        return None
    tok, m, user = row
    if tok.revoked_at is not None or not user.is_active:
        return None
    tok.last_used_at = utcnow()
    return _principal(user, m, via="api_token", scopes=frozenset(tok.scopes))
