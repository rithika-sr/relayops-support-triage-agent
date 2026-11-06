"""Check local prerequisites and service health without changing anything."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def report(label: str, good: bool, detail: str = "") -> None:
    global ok
    ok = ok and good
    print(f"{'OK  ' if good else 'FAIL'} {label}{(': ' + detail) if detail else ''}")


def env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def get(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 - local URLs only
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


e = env()
report(".env present", bool(e), "run `make setup`" if not e else "")
if e:
    report(".env permissions 0600", stat.S_IMODE((ROOT / ".env").stat().st_mode) == 0o600)
for tool in ("uv", "node", "npm", "docker", "ollama"):
    report(f"{tool} installed", shutil.which(tool) is not None)
py = subprocess.run(["uv", "run", "--directory", str(ROOT / "backend"), "python", "-c", "import sys;print(sys.version.split()[0])"],
                    capture_output=True, text=True)
report("backend Python 3.12", py.stdout.startswith("3.12"), py.stdout.strip() or py.stderr.strip()[:120])
db_port = int(e.get("RELAYOPS_DB_PORT", "5440"))
report(f"postgres on {db_port}", port_open(db_port), "run `make up`")
tags = get(e.get("RELAYOPS_OLLAMA_BASE_URL", "http://127.0.0.1:11434") + "/api/tags")
report("ollama reachable", tags is not None)
if tags:
    names = {m["name"] for m in tags.get("models", [])}
    for model in (e.get("RELAYOPS_CHAT_MODEL", "qwen3:4b-instruct"), e.get("RELAYOPS_EMBED_MODEL", "embeddinggemma")):
        report(f"model {model}", model in names or f"{model}:latest" in names, "ollama pull " + model)
api = get(f"http://127.0.0.1:{e.get('RELAYOPS_API_PORT', '8020')}/api/health")
report("api health", api is not None and api.get("status") == "ok", "start with `make dev`" if api is None else "")
report("web reachable", port_open(int(e.get("RELAYOPS_WEB_PORT", "3020"))), "start with `make dev`")
creds = ROOT / ".local" / "demo-credentials.json"
report("demo credentials (ignored file)", creds.exists(), "run `make seed`" if not creds.exists() else "")
if creds.exists():
    report("credentials permissions 0600", stat.S_IMODE(creds.stat().st_mode) == 0o600)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(creds)], cwd=ROOT, capture_output=True)
    report("credentials not tracked by git", tracked.returncode != 0)
print("doctor:", "all checks passed" if ok else "some checks failed")
sys.exit(0 if ok or os.environ.get("DOCTOR_SOFT") else 1)
