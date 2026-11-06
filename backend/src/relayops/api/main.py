from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from relayops.agents.llm import ModelUnavailable
from relayops.api import mcp as mcp_endpoint
from relayops.api.routers import (
    auth,
    claim_labels,
    integrations,
    investigations,
    knowledge,
    operations,
    settings,
    tickets,
)
from relayops.core import logs
from relayops.core.config import get_settings
from relayops.core.db import get_engine, session_scope
from relayops.core.instance import require_mode
from relayops.domain.scope import AccessDenied, Conflict, NotFound, ValidationFailed

log = logging.getLogger("relayops.api")


def _migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    logs.configure(s.log_format, s.log_level)
    # Refuse to serve when the configured data mode does not match the database (or settings are unsafe).
    with session_scope() as db:
        mode = require_mode(db)
    log.info("RelayOps API serving %s data", mode)
    async with mcp_endpoint.mounted.running():
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RelayOps API", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan
    )

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(AccessDenied)
    async def _ad(_: Request, exc: AccessDenied) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValidationFailed)
    async def _vf(_: Request, exc: ValidationFailed) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Conflict)
    async def _cf(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ModelUnavailable)
    async def _mu(_: Request, exc: ModelUnavailable) -> JSONResponse:
        return JSONResponse({"detail": f"local model unavailable: {exc}", "code": "model_unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def _rv(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": "invalid request", "errors": errors}, status_code=422)

    @app.get("/api/instance")
    def instance() -> dict[str, object]:
        mode = get_settings().data_mode
        labels = {
            "operational": None,
            "demo": "Demo instance: every record here is synthetic sample data.",
            "test": "Test instance: records are test fixtures.",
        }
        return {"data_mode": mode, "banner": labels[mode]}

    @app.middleware("http")
    async def request_log(request: Request, call_next: Any) -> Any:
        incoming = request.headers.get("x-request-id") or ""
        rid = incoming if logs.REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = logs.request_id.set(rid)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
            raise
        finally:
            logs.request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        if not request.url.path.startswith(("/api/health", "/api/ready")):
            token = logs.request_id.set(rid)
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                },
            )
            logs.request_id.reset(token)
        return response

    @app.get("/api/health")
    def health() -> dict[str, object]:
        """Liveness: the process is serving. Does not touch dependencies."""
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready() -> JSONResponse:
        """Readiness: the database answers, migrations are at head, and the recorded data mode matches."""
        checks: dict[str, dict[str, object]] = {}
        try:
            with get_engine().connect() as c:
                c.execute(text("select 1"))
                current = c.execute(text("select version_num from alembic_version")).scalar()
            checks["database"] = {"ok": True}
            head = _migration_head()
            checks["migrations"] = {"ok": current == head, "current": current, "head": head}
            with session_scope() as db:
                checks["data_mode"] = {"ok": True, "mode": require_mode(db)}
        except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
            checks.setdefault("database", {"ok": False, "error": exc.__class__.__name__})
            checks.setdefault("data_mode", {"ok": False, "error": str(exc)[:200]})
        checks["mcp"] = {"ok": mcp_endpoint.mounted.app is not None}
        ok = all(bool(v["ok"]) for v in checks.values())
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503
        )

    for r in (
        auth.router,
        tickets.router,
        knowledge.router,
        investigations.router,
        operations.router,
        integrations.router,
        claim_labels.router,
        settings.router,
    ):
        app.include_router(r, prefix="/api")
    # Read-only MCP over streamable HTTP at /mcp; bearer API tokens with the mcp:read scope only.
    app.mount("/mcp", mcp_endpoint.mounted)
    return app


app = create_app()
