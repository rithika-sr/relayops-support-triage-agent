"""Verify a backup restores. Restores into a scratch database, reports what it found, then drops the scratch DB.

Never restores over a working database. Usage: python3 scripts/restore_check.py [path/to/file.dump]
(default: the newest dump in data/backups/).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = "relayops_restore_check"
TABLES = ("organizations", "users", "tickets", "ticket_messages", "knowledge_documents", "investigation_runs",
          "proposals", "action_ledger", "audit_events")


def psql(db: str, sql: str) -> str:
    out = subprocess.run(["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "psql", "-tAqU", "relayops",
                          "-d", db, "-c", sql], capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        raise SystemExit(f"psql failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def main() -> int:
    dumps = sorted((ROOT / "data" / "backups").glob("*.dump"), key=lambda p: p.stat().st_mtime)
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (dumps[-1] if dumps else None)
    if path is None or not path.exists():
        print("no backup found; run make backup first")
        return 1
    psql("postgres", f"drop database if exists {SCRATCH} with (force)")
    psql("postgres", f"create database {SCRATCH}")
    try:
        with path.open("rb") as fh:
            r = subprocess.run(["docker", "compose", "--env-file", ".env", "exec", "-T", "db", "pg_restore", "-U",
                                "relayops", "-d", SCRATCH, "--no-owner", "--exit-on-error"], stdin=fh,
                               capture_output=True, cwd=ROOT)
        if r.returncode != 0:
            print(f"RESTORE FAILED for {path.name}: {r.stderr.decode(errors='replace')[:500]}")
            return 1
        def exists(t: str) -> bool:
            return psql(SCRATCH, f"select to_regclass('public.{t}') is not null") == "t"

        version = psql(SCRATCH, "select version_num from alembic_version")
        mode = psql(SCRATCH, "select data_mode from instance_metadata") if exists("instance_metadata") else ""
        counts = {t: psql(SCRATCH, f"select count(*) from {t}") if exists(t) else "absent (older schema)"
                  for t in TABLES}
        print(f"restored {path.name}: migration {version}, data mode {mode or 'not initialized'}")
        for t, n in counts.items():
            print(f"  {t:22} {n}")
        return 0
    finally:
        psql("postgres", f"drop database if exists {SCRATCH} with (force)")


if __name__ == "__main__":
    sys.exit(main())
