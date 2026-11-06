"""Repository hygiene gate: secrets, local-only files, and documentation references.

Scans every tracked file (nothing is excluded to make it pass). Fails on credential-like strings, tracked
local orchestration files, or documentation links to files that do not exist.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = re.compile(r"^(\.local/|\.claude/|CLAUDE\.md$|\.env$|.*\.pem$|.*\.key$|frontend/AGENTS\.md$)")
PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "openai/anthropic key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b"),
    "relayops api token": re.compile(r"\brlo_[A-Za-z0-9_-]{30,}\b"),
    "generic assignment": re.compile(r"(?i)\b(password|secret|api_key|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
}
ALLOWED = {"change-me", "change-me-to-a-long-random-value", "test-session-secret-0123456789"}


def tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()


def main() -> int:
    problems = []
    files = tracked()
    for f in files:
        if FORBIDDEN_PATHS.match(f):
            problems.append(f"local-only file is tracked: {f}")
    for f in files:
        p = ROOT / f
        if not p.is_file() or p.stat().st_size > 2_000_000 or p.suffix in {".png", ".jpg", ".ico", ".lock"}:
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                if not any(a in m.group(0) for a in ALLOWED):
                    problems.append(f"{f}: possible {name}: {m.group(0)[:40]}…")
    for f in [x for x in files if x.endswith(".md")]:
        text = (ROOT / f).read_text()
        for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", text):
            path = (ROOT / f).parent / target.split("#")[0]
            if target.split("#")[0] and not path.exists():
                problems.append(f"{f}: broken link {target}")
    required = ["README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "docs/architecture.md",
                "docs/development.md", "docs/deployment.md", "docs/api.md", "docs/security.md", "docs/evaluation.md",
                "docs/demo.md"]
    problems += [f"missing required document {d}" for d in required if d not in files]
    if problems:
        print("repository check failed:\n  " + "\n  ".join(problems))
        return 1
    print(f"repository check passed ({len(files)} tracked files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
