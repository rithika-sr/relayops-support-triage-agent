"""Request dependencies: database session, authenticated principal, CSRF and origin checks."""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from relayops.core.config import get_settings
from relayops.core.db import new_session
from relayops.core.security import constant_eq, csrf_for_session
from relayops.domain.scope import Principal
from relayops.services import auth as auth_service

SESSION_COOKIE = "relayops_session"
CSRF_COOKIE = "relayops_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Function scope: commit before the response is sent, so a client's next request sees the write.
DB = Depends(get_db, scope="function")


def allowed_origins() -> set[str]:
    s = get_settings()
    out = {s.web_origin.rstrip("/"), s.api_origin.rstrip("/")}
    for o in list(out):
        u = urlparse(o)
        if u.hostname == "localhost":
            out.add(o.replace("localhost", "127.0.0.1"))
    return out


def check_origin(request: Request) -> None:
    """Reject cross-site mutations. Browsers always send Origin on cross-origin POSTs."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in allowed_origins():
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


def require_pre_session_guard(request: Request) -> None:
    """Login/registration have no session yet: require same-origin plus a custom header (forces CORS preflight)."""
    check_origin(request)
    if request.headers.get("x-requested-with") != "relayops":
        raise HTTPException(status_code=403, detail="missing request header")


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def current_principal(request: Request, db: Session = DB) -> Principal:
    if _bearer(request):
        # API tokens are read-only MCP credentials and never authenticate ordinary REST endpoints.
        raise HTTPException(status_code=401, detail="API tokens are only accepted by the read-only MCP endpoint")
    token = request.cookies.get(SESSION_COOKIE, "")
    resolved = auth_service.resolve_session(db, token)
    if resolved is None:
        raise HTTPException(status_code=401, detail="sign in required")
    principal, _ = resolved
    if request.method not in SAFE_METHODS:
        check_origin(request)
        sent = request.headers.get(CSRF_HEADER, "")
        expected = csrf_for_session(token, get_settings().session_secret)
        if not sent or not constant_eq(sent, expected):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    request.state.principal = principal
    return principal


def staff_principal(p: Principal = Depends(current_principal)) -> Principal:
    if not p.is_staff:
        raise HTTPException(status_code=403, detail="staff access required")
    return p


def admin_principal(p: Principal = Depends(current_principal)) -> Principal:
    if not p.is_admin:
        raise HTTPException(status_code=403, detail="organization admin access required")
    return p


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def safe_redirect(target: str | None, role: str) -> str:
    """Only same-site relative paths inside the area the role may use; otherwise the role's home."""
    home = "/portal" if role == "customer" else "/app"
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target or "://" in target:
        return home
    if any(c in target for c in "\r\n\t"):
        return home
    allowed = ("/portal",) if role == "customer" else ("/app",)
    return target if target.startswith(allowed) else home
