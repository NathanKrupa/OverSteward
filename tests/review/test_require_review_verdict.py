# ABOUTME: Runs the require_review_verdict gate against every stored PR-body fixture.
# ABOUTME: The gate ships with the bodies that make it red — a green it cannot fail is decoration.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "lint" / "require_review_verdict.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "review_verdict"

#: Every fixture, with the exit code the gate must produce for it. The reds are
#: the point: each one is a way an author can arrive at a PR without a review.
EXPECTED = {
    "pass.md": 0,
    "pass_with_findings.md": 0,
    "block.md": 1,
    "missing.md": 1,
    "prose_only.md": 1,
    "inconsistent.md": 1,
    "unfilled_template.md": 1,
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args], capture_output=True, text=True, check=False
    )


def test_every_fixture_on_disk_is_accounted_for() -> None:
    """A fixture nobody asserts on is a fixture that proves nothing."""
    on_disk = {path.name for path in FIXTURES.glob("*.md")}
    assert on_disk == set(EXPECTED), f"unlisted fixtures: {on_disk ^ set(EXPECTED)}"


def test_the_fixture_set_contains_reds() -> None:
    """Guards the suite against a future where every fixture is a pass."""
    assert sum(1 for code in EXPECTED.values() if code != 0) >= 5


@pytest.mark.parametrize(("name", "expected"), sorted(EXPECTED.items()))
def test_gate_exit_code_for_fixture(name: str, expected: int) -> None:
    result = _run("--body-file", str(FIXTURES / name))
    assert result.returncode == expected, (
        f"{name}: expected exit {expected}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_a_failing_fixture_names_what_is_wrong_rather_than_exiting_quietly() -> None:
    result = _run("--body-file", str(FIXTURES / "missing.md"))
    assert "reviewer-verdict" in result.stderr


def test_an_unreadable_body_exits_two_and_never_shares_a_code_with_a_pass() -> None:
    result = _run("--body-file", str(FIXTURES / "does-not-exist.md"))
    assert result.returncode == 2
    assert "COULD NOT LOOK" in result.stderr


def test_the_gate_refuses_to_run_without_a_source() -> None:
    """No default source: a gate invoked wrongly must not certify anything."""
    assert _run().returncode != 0
