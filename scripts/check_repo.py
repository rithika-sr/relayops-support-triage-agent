"""Repository hygiene gate: credential patterns, tracked local-only files, and documentation references.

Coverage (reported on every run): every tracked path is checked against the local-only rules; every tracked file
that decodes as UTF-8 is content-scanned regardless of size; files that do not decode (images, PDFs, other
binaries) are counted as not content-scanned. Git history is covered separately by gitleaks in CI.

Known non-secrets are exempt only by an exact (path, rule, value) entry; a longer string that merely contains an
allowed value is still reported. Matches are printed as path, line, rule, and a short hash, never the value.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = re.compile(
    r"^(\.local/|\.claude/|CLAUDE\.md$|\.env$|\.env\.(?!example$|test\.example$)|.*\.pem$|.*\.key$|"
    r"frontend/AGENTS\.md$|data/backups/|data/runtime/|data/uploads/)"
)
PATTERNS: dict[str, re.Pattern[str]] = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "aws key": re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    "slack token": re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"),
    "llm api key": re.compile(r"\b(sk-(?:ant-)?[A-Za-z0-9_-]{20,})"),
    "relayops api token": re.compile(r"\b(rlo_[A-Za-z0-9_-]{30,})"),
    "webhook signing secret": re.compile(r"\b(whsec_[A-Za-z0-9_-]{30,})"),
    "generic assignment": re.compile(
        r"(?i)\b(?:password|passwd|secret|api_key|token)\w*\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]"
    ),
}


@dataclass(frozen=True)
class Allowed:
    path: str
    rule: str
    value: str


# Exact known non-secrets used by the test suite.
ALLOWLIST = {
    Allowed("backend/tests/factories.py", "generic assignment", "correct-horse-battery-staple"),
    Allowed(".gitleaks.toml", "generic assignment", "correct-horse-battery-staple"),  # the matching gitleaks entry
}
REQUIRED_DOCS = ["README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"]


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    fingerprint: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: possible {self.rule} (sha256:{self.fingerprint})"


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p.decode() for p in out.split(b"\0") if p]


def scan_text(path: str, text: str, allowlist: set[Allowed] = ALLOWLIST) -> list[Finding]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, rx in PATTERNS.items():
            for m in rx.finditer(line):
                value = m.group(1) if m.groups() else m.group(0)
                if Allowed(path, rule, value) in allowlist:
                    continue
                findings.append(Finding(path, lineno, rule, hashlib.sha256(value.encode()).hexdigest()[:12]))
    return findings


def main() -> int:
    files = tracked()
    problems: list[str] = [f"local-only file is tracked: {f}" for f in files if FORBIDDEN_PATHS.match(f)]
    findings: list[Finding] = []
    not_scanned: list[str] = []
    scanned = 0
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            not_scanned.append(f)
            continue
        scanned += 1
        findings += scan_text(f, text)
    for f in (x for x in files if x.endswith(".md")):
        text = (ROOT / f).read_text()
        for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", text):
            path = (ROOT / f).parent / target.split("#")[0]
            if target.split("#")[0] and not path.exists():
                problems.append(f"{f}: broken link {target}")
    problems += [f"missing required document {d}" for d in REQUIRED_DOCS if d not in files]
    print(f"paths checked: {len(files)}; content-scanned (UTF-8): {scanned}; "
          f"not content-scanned (binary): {len(not_scanned)}")
    if not_scanned:
        kinds: dict[str, int] = {}
        for f in not_scanned:
            ext = Path(f).suffix or "(none)"
            kinds[ext] = kinds.get(ext, 0) + 1
        print("  binary by extension: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    if problems or findings:
        print("repository check failed:")
        for item in [*problems, *map(str, findings)]:
            print(f"  {item}")
        return 1
    print("repository check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
