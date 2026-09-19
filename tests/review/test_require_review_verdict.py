# ABOUTME: Runs the require_review_verdict gate against every stored PR-body fixture.
# ABOUTME: The gate ships with the bodies that make it red — a green it cannot fail is decoration.

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from oversteward.review_verdict import GATE_LIVE_FROM

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


def _run(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
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


# ---------------------------------------------------------------------------
# The `--pr` path — what the CI job actually runs (OS#437).
#
# `gh` is stubbed rather than called: these assert the gate's handling of a real
# API payload, including the `created_at` the non-retroactivity cutoff reads.
# ---------------------------------------------------------------------------

CUTOFF = datetime.fromisoformat(GATE_LIVE_FROM)
GOVERNED = (CUTOFF + timedelta(days=1)).isoformat().replace("+00:00", "Z")
PREDATES = (CUTOFF - timedelta(days=1)).isoformat().replace("+00:00", "Z")


def _gh_stub(
    tmp_path: Path, payload: str, *, exit_code: int = 0
) -> dict[str, str]:
    """An environment whose `gh` answers the REST call with ``payload``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    answer = tmp_path / "payload.json"
    answer.write_text(payload, encoding="utf-8")
    stub = bin_dir / "gh"
    stub.write_text(f'#!/bin/sh\ncat "{answer}"\nexit {exit_code}\n', encoding="utf-8")
    stub.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def _payload(body_fixture: str, created_at: str) -> str:
    body = (FIXTURES / body_fixture).read_text(encoding="utf-8")
    return json.dumps({"number": 1, "body": body, "created_at": created_at})


class TestAgainstAPullRequestBody:
    """The three outcomes the CI job maps, read from a PR payload."""

    def test_a_governed_pr_without_a_verdict_is_red(self, tmp_path: Path) -> None:
        env = _gh_stub(tmp_path, _payload("missing.md", GOVERNED))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 1, result.stderr
        assert "reviewer-verdict" in result.stderr

    def test_a_governed_pr_with_a_block_verdict_is_red(self, tmp_path: Path) -> None:
        env = _gh_stub(tmp_path, _payload("block.md", GOVERNED))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 1, result.stderr
        assert "BLOCK" in result.stderr

    def test_a_governed_pr_with_findings_but_no_block_is_green(
        self, tmp_path: Path
    ) -> None:
        env = _gh_stub(tmp_path, _payload("pass_with_findings.md", GOVERNED))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 0, result.stderr

    def test_a_pr_predating_the_gate_is_neither_a_pass_nor_a_failure(
        self, tmp_path: Path
    ) -> None:
        """No verdict, but opened before the gate existed — exit 3, said plainly."""
        env = _gh_stub(tmp_path, _payload("missing.md", PREDATES))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 3, f"{result.returncode}: {result.stdout}{result.stderr}"
        assert "NOT APPLICABLE" in result.stdout

    def test_a_pr_predating_the_gate_with_a_block_verdict_is_still_red(
        self, tmp_path: Path
    ) -> None:
        """Non-retroactivity excuses an absent verdict, never a present refusal.

        Before OS#444 the cutoff was consulted first, so this exact payload —
        an explicit BLOCK on a PR opened a day before the gate — exited 3 and
        printed "Nothing was judged" over a review that had judged and refused.
        """
        env = _gh_stub(tmp_path, _payload("block.md", PREDATES))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 1, (
            f"expected exit 1, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "BLOCK" in result.stderr

    def test_a_pr_predating_the_gate_with_a_pass_verdict_is_green(
        self, tmp_path: Path
    ) -> None:
        """A present, well-formed pass is reported as the pass it is, not as
        an unjudged skip — the exemption's own message claims nothing was
        judged, and here something was."""
        env = _gh_stub(tmp_path, _payload("pass_with_findings.md", PREDATES))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_a_pr_predating_the_gate_with_a_malformed_block_is_red(
        self, tmp_path: Path
    ) -> None:
        """A block that exists but says nothing actionable was still written by
        someone; only an *absent* verdict is excused."""
        env = _gh_stub(tmp_path, _payload("unfilled_template.md", PREDATES))
        result = _run("--pr", "1", env=env)
        assert result.returncode == 1, (
            f"expected exit 1, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_a_pr_carrying_no_creation_time_is_still_judged(
        self, tmp_path: Path
    ) -> None:
        """Fail closed — a payload the cutoff cannot read is not an exemption."""
        env = _gh_stub(tmp_path, json.dumps({"body": "no verdict here"}))
        assert _run("--pr", "1", env=env).returncode == 1

    def test_an_unreachable_gh_is_could_not_look_not_a_pass(
        self, tmp_path: Path
    ) -> None:
        env = _gh_stub(tmp_path, "", exit_code=1)
        result = _run("--pr", "1", env=env)
        assert result.returncode == 2
        assert "COULD NOT LOOK" in result.stderr
