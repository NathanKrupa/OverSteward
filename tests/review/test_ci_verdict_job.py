# ABOUTME: Pins the CI wiring of the verdict gate — the job exists, and a body edit re-runs it.
# ABOUTME: CI cannot test its own triggers, so a missing `edited` type fails silently and forever.

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB = "reviewer-verdict"


@pytest.fixture(scope="module")
def workflow() -> dict:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads a bare `on:` key as the boolean True; PyYAML follows it.
    parsed["on"] = parsed.get("on", parsed.get(True))
    return parsed


@pytest.fixture(scope="module")
def verdict_job(workflow: dict) -> dict:
    assert JOB in workflow["jobs"], f"no `{JOB}` job in {WORKFLOW.name}"
    return workflow["jobs"][JOB]


def test_the_job_runs_the_gate_against_this_pull_request(verdict_job: dict) -> None:
    commands = "\n".join(step.get("run", "") for step in verdict_job["steps"])
    assert "scripts/lint/require_review_verdict.py" in commands
    assert "--pr" in commands


def test_the_job_never_fires_on_a_push(verdict_job: dict) -> None:
    """A push to master has no PR body; judging one would be judging nothing."""
    assert "github.event_name == 'pull_request'" in verdict_job["if"]


def test_a_body_edit_re_runs_the_gate(workflow: dict) -> None:
    """The verdict is pasted in after opening. Without `edited` the check stays
    red however good the verdict is, and a check that cannot go green is one the
    estate learns to ignore."""
    assert "edited" in workflow["on"]["pull_request"]["types"]


def test_a_body_edit_does_not_re_run_the_whole_suite(workflow: dict) -> None:
    """`edited` fires on every body keystroke-save; only the cheap job wants it."""
    for name, job in workflow["jobs"].items():
        if name == JOB:
            continue
        assert "edited" in job.get("if", ""), f"job `{name}` re-runs on a body edit"
