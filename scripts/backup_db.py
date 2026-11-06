"""pg_dump one database (custom format) into data/backups/. Restore: pg_restore -d <db> --clean <file>."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main(url: str) -> int:
    name = urlparse(url.replace("postgresql+psycopg://", "postgresql://")).path.lstrip("/")
    out = ROOT / "data" / "backups" / f"{name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.dump"
    out.parent.mkdir(parents=True, exist_ok=True)
    exists = subprocess.run(["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "psql", "-tAqU", "relayops",
                             "-d", "postgres", "-c", f"select 1 from pg_database where datname = '{name}'"],
                            capture_output=True, text=True, cwd=ROOT)
    if exists.stdout.strip() != "1":
        print(f"database {name} does not exist; nothing to back up")
        return 0
    with out.open("wb") as fh:
        subprocess.run(["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "pg_dump", "-U", "relayops", "-Fc",
                        name], stdout=fh, check=True, cwd=ROOT)
    print(f"backup written: {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
    return 0


def _url_from_env(var: str) -> str:
    """Read a URL by variable name from the environment or .env, so secrets never appear on command lines."""
    import os
    from pathlib import Path

    if os.environ.get(var):
        return os.environ[var]
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text().splitlines():
        if line.startswith(var + "="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{var} is not set; run make setup")


if __name__ == "__main__":
    sys.exit(main(_url_from_env(sys.argv[1])))
