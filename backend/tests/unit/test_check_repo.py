"""Regression tests for the repository secret scan's exact allowlist and redaction."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_repo", ROOT / "scripts" / "check_repo.py")
assert spec and spec.loader
check_repo = importlib.util.module_from_spec(spec)
sys.modules["check_repo"] = check_repo  # dataclasses need the module registered
spec.loader.exec_module(check_repo)

# Samples are assembled at runtime so this file does not itself contain credential-shaped literals.
Q = '"'
FIXTURE = "PASSWORD = " + Q + "correct-horse-battery-staple" + Q


def test_exact_fixture_value_is_allowed_only_in_its_file():
    assert check_repo.scan_text("backend/tests/factories.py", FIXTURE) == []
    assert check_repo.scan_text("backend/src/relayops/x.py", FIXTURE)


def test_values_that_only_contain_an_allowed_string_are_reported():
    for variant in (
        "PASSWORD = " + Q + "correct-horse-battery-staple" + "-PRODKEY9" + Q,
        "PASSWORD = " + Q + "x" + "correct-horse-battery-staple" + Q,
    ):
        assert check_repo.scan_text("backend/tests/factories.py", variant), variant


def test_findings_are_redacted():
    secret = "ghp_" + "A" * 36
    [finding] = check_repo.scan_text("README.md", f"token here {secret}")
    assert secret not in str(finding) and finding.rule == "github token" and finding.line == 1


def test_known_credential_shapes_are_detected():
    samples = [
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        "AKIA" + "B" * 16,
        "sk-ant-" + "c" * 30,
        "rlo_" + "d" * 40,
        "whsec_" + "e" * 40,
        "api_key = " + Q + "abcdefghijklmnop" + Q,
    ]
    for s in samples:
        assert check_repo.scan_text("x.txt", s), s


def test_local_only_paths_are_forbidden():
    for path in (".env", ".env.local", ".local/demo-credentials.json", "CLAUDE.md", "data/backups/x.dump"):
        assert check_repo.FORBIDDEN_PATHS.match(path), path
    for path in (".env.example", "docs/security.md"):
        assert not check_repo.FORBIDDEN_PATHS.match(path), path
