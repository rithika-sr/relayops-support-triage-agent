"""Create the database named in a SQLAlchemy URL if it does not exist. Never drops or alters existing data."""

from __future__ import annotations

import subprocess
import sys
from urllib.parse import urlparse


def main(url: str) -> int:
    u = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    name = u.path.lstrip("/")
    if not name.replace("_", "").isalnum():
        print(f"refusing unexpected database name {name!r}")
        return 2
    exists = subprocess.run(
        ["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "psql", "-tAqU", "relayops", "-d", "postgres",
         "-c", f"select 1 from pg_database where datname = '{name}'"], capture_output=True, text=True, check=True)
    if exists.stdout.strip() != "1":
        subprocess.run(["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "psql", "-qU", "relayops",
                        "-d", "postgres", "-c", f'create database "{name}"'], check=True)
        print(f"created database {name}")
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
