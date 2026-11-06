"""Structured logging. `RELAYOPS_LOG_FORMAT=json` emits one JSON object per line; `text` is for humans.

Each API request gets an ID (taken from a well-formed `X-Request-ID` or generated) that is attached to every
log line for that request and returned in the response header. Log lines never include request bodies,
cookies, authorization headers, or query strings.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime

request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class JsonFormatter(logging.Formatter):
    FIELDS = ("method", "path", "status", "duration_ms", "worker_id", "job_id", "run_id")

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id.get()
        if rid:
            out["request_id"] = rid
        for f in self.FIELDS:
            if hasattr(record, f):
                out[f] = getattr(record, f)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure(fmt: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    enable_app_loggers()


def enable_app_loggers() -> None:
    """Alembic's fileConfig disables loggers that already exist; RelayOps loggers must keep working."""
    for name, lg in logging.root.manager.loggerDict.items():
        if name.startswith("relayops") and isinstance(lg, logging.Logger):
            lg.disabled = False
