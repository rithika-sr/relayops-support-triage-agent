"""Create a local `.env` with freshly generated secrets. Existing values are never overwritten."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def main() -> int:
    existing: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()

    db_port = existing.get("RELAYOPS_DB_PORT", "5440")
    pg_password = existing.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(24)
    defaults = {
        "POSTGRES_PASSWORD": pg_password,
        "RELAYOPS_DB_PORT": db_port,
        "RELAYOPS_API_PORT": "8020",
        "RELAYOPS_WEB_PORT": "3020",
        # Operational data (default). Starts empty: no sample customers, tickets, or activity.
        "RELAYOPS_DATA_MODE": "operational",
        "RELAYOPS_DATABASE_URL": f"postgresql+psycopg://relayops:{pg_password}@127.0.0.1:{db_port}/relayops",
        # Separate database for the labeled demo instance (make seed-demo, make demo-dev).
        "RELAYOPS_DEMO_DATABASE_URL": f"postgresql+psycopg://relayops:{pg_password}@127.0.0.1:{db_port}/relayops_demo",
        "RELAYOPS_SESSION_SECRET": secrets.token_urlsafe(48),
        "RELAYOPS_WEB_ORIGIN": "http://localhost:3020",
        "RELAYOPS_API_ORIGIN": "http://localhost:8020",
        "RELAYOPS_LLM_PROVIDER": "ollama",
        "RELAYOPS_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "RELAYOPS_CHAT_MODEL": "qwen3:4b-instruct",
        "RELAYOPS_EMBED_MODEL": "embeddinggemma",
    }
    added = [k for k in defaults if k not in existing]
    merged = {**defaults, **existing}
    ENV.write_text("".join(f"{k}={v}\n" for k, v in merged.items()))
    os.chmod(ENV, 0o600)
    print(f".env ready ({'added ' + ', '.join(added) if added else 'no changes'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
