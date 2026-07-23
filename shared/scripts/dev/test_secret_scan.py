# ABOUTME: Tests for the Tier-1 secret-scan gate (scripts/dev/secret_scan.py).
# ABOUTME: Covers report reduction, secret non-leakage, docker-mode command shape, and exit codes.

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# A gitleaks report row carrying a (masked) secret — the test proves the
# reducer never surfaces the value even when the field is present.
SECRET_MARKER = "sk_live_SHOULD_NEVER_APPEAR_ABCDEF123456"


def _load_scanner():
    """Load the deployed gate by file path (no package install needed)."""
    rel = Path("scripts") / "dev" / "secret_scan.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("secret_scan", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"could not locate {rel} above {__file__}")


@pytest.fixture(scope="module")
def scan():
    return _load_scanner()


# --- report reduction -------------------------------------------------------


def test_empty_report_is_no_findings(scan):
    assert scan.parse_report("") == []
    assert scan.parse_report("[]") == []


def test_parse_reduces_to_rule_file_line(scan):
    report = json.dumps(
        [
            {"RuleID": "stripe-access-token", "File": "a.py", "StartLine": 12},
            {"RuleID": "generic-api-key", "File": "b/c.py", "StartLine": 3},
        ]
    )
    findings = scan.parse_report(report)
    assert [(f.rule, f.file, f.line) for f in findings] == [
        ("stripe-access-token", "a.py", 12),
        ("generic-api-key", "b/c.py", 3),
    ]


def test_finding_never_carries_the_secret_value(scan):
    """Even with Secret/Match populated, the reduced finding cannot leak them."""
    report = json.dumps(
        [{"RuleID": "r", "File": "f", "StartLine": 1, "Secret": SECRET_MARKER, "Match": SECRET_MARKER}]
    )
    findings = scan.parse_report(report)
    rendered = findings[0].render()
    assert SECRET_MARKER not in rendered
    assert not hasattr(findings[0], "secret")


# --- docker command shape ---------------------------------------------------


def test_staged_command_is_protect_redacted_readonly(scan):
    cmd = scan.build_gitleaks_cmd(
        Path("/repo"), Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=True, rev_range=None
    )
    assert "protect" in cmd
    assert "--staged" in cmd
    assert "--redact" in cmd
    assert any(a.endswith(":ro") for a in cmd), "repo must mount read-only"


def test_range_command_is_detect_with_log_opts(scan):
    cmd = scan.build_gitleaks_cmd(
        Path("/repo"), Path("/out/report.json"), scan.DEFAULT_IMAGE, staged=False, rev_range="a..b"
    )
    assert "detect" in cmd
    assert "--log-opts=a..b" in cmd
    assert "--redact" in cmd
    assert "--staged" not in cmd


# --- exit-code / fail-open-vs-closed logic ----------------------------------


def test_docker_absent_skips_when_not_required(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    assert scan.main(["--staged"]) == 0


def test_docker_absent_fails_closed_when_required(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: False)
    monkeypatch.setenv("SECRET_SCAN_REQUIRED", "1")
    assert scan.main(["--staged"]) == 2


def test_findings_fail_the_gate(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(
        scan, "run_scan", lambda *a, **k: [scan.Finding("generic-api-key", "x.py", 9)]
    )
    assert scan.main(["--staged"]) == 1


def test_clean_scan_passes(scan, monkeypatch):
    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(scan, "run_scan", lambda *a, **k: [])
    assert scan.main(["--staged"]) == 0


def test_scan_error_skips_unless_required(scan, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("gitleaks produced no report: boom")

    monkeypatch.setattr(scan, "docker_available", lambda: True)
    monkeypatch.setattr(scan, "run_scan", _boom)
    monkeypatch.delenv("SECRET_SCAN_REQUIRED", raising=False)
    assert scan.main(["--staged"]) == 0
    monkeypatch.setenv("SECRET_SCAN_REQUIRED", "1")
    assert scan.main(["--staged"]) == 2
