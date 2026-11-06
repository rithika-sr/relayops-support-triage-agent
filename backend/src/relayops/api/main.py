from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from relayops.agents.llm import ModelUnavailable
from relayops.api.routers import auth, investigations, knowledge, operations, settings, tickets
from relayops.core.config import get_settings
from relayops.core.db import get_engine
from relayops.domain.scope import AccessDenied, Conflict, NotFound, ValidationFailed

log = logging.getLogger("relayops.api")


def create_app() -> FastAPI:
    app = FastAPI(title="RelayOps API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

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

    @app.get("/api/health")
    def health() -> dict[str, object]:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
        return {"status": "ok", "env": get_settings().env}

    for r in (auth.router, tickets.router, knowledge.router, investigations.router, operations.router, settings.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
