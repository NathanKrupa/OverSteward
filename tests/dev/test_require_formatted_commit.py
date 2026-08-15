# ABOUTME: Tests the canonical verify-time gate (shared/scripts/dev/require_formatted_commit.py).
# ABOUTME: Covers the residue case that shipped unformatted bytes past a green local verify (OS#78).

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.dev.conftest import (
    FORMATTED,
    UNFORMATTED,
    Repo,
    StandInFormatter,
    load_dev_script,
    run_gate,
)

SCRIPT = "require_formatted_commit.py"

OK = 0
NOT_CLEAN = 1
UNUSABLE = 2


@pytest.fixture(scope="module")
def gate():
    return load_dev_script(SCRIPT)


def _run(repo: Repo, formatter: StandInFormatter, *args: str):
    return run_gate(SCRIPT, repo, "--formatter", formatter.command, *args)


def test_passes_when_the_committed_tree_is_already_formatted(repo, formatter):
    repo.write("app.py", FORMATTED)
    repo.commit_all()

    result = _run(repo, formatter)

    assert result.returncode == OK
    assert "ok:" in result.stdout


def test_fails_on_formatter_residue_left_by_this_run(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.commit_all()

    result = _run(repo, formatter)

    assert result.returncode == NOT_CLEAN
    assert "app.py" in result.stderr
    assert "formatter residue" in result.stderr


def test_residue_report_names_the_amend_fix(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.commit_all()

    result = _run(repo, formatter)

    assert "git commit --amend" in result.stderr


def test_fails_when_uncommitted_work_predates_the_run(repo, formatter):
    repo.write("app.py", FORMATTED)
    repo.commit_all()
    repo.write("app.py", "x = 2\n")

    result = _run(repo, formatter)

    assert result.returncode == NOT_CLEAN
    assert "uncommitted work" in result.stderr
    assert "formatter residue" not in result.stderr


def test_separates_residue_from_work_that_was_already_dirty(repo, formatter):
    repo.write("committed.py", UNFORMATTED)
    repo.write("dirty.py", FORMATTED)
    repo.commit_all()
    repo.write("dirty.py", "y = 2\n")

    result = _run(repo, formatter)
    residue, preexisting = result.stderr.split("modified before this run")

    assert result.returncode == NOT_CLEAN
    assert "committed.py" in residue
    assert "dirty.py" in preexisting


def test_leaves_the_tree_formatted_even_when_it_fails(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.commit_all()

    _run(repo, formatter)

    assert repo.read("app.py") == FORMATTED


def test_formats_only_the_requested_targets(repo, formatter):
    repo.write("kept/app.py", UNFORMATTED)
    repo.write("skipped/app.py", UNFORMATTED)
    repo.commit_all()

    _run(repo, formatter, "kept")

    assert formatter.formatted_paths == {"kept/app.py"}
    assert repo.read("skipped/app.py") == UNFORMATTED


def test_exits_unusable_when_no_formatter_is_available(repo, formatter):
    repo.write("app.py", FORMATTED)
    repo.commit_all()

    result = run_gate(SCRIPT, repo, "--formatter", "")

    assert result.returncode == UNUSABLE
    assert "no formatter found" in result.stderr


def test_exits_unusable_when_the_formatter_itself_fails(repo, formatter):
    repo.write("app.py", FORMATTED)
    repo.commit_all()

    broken = f"{sys.executable} -c raise-a-syntax-error"
    result = run_gate(SCRIPT, repo, "--formatter", broken)

    assert result.returncode == UNUSABLE
    assert "formatter exited" in result.stderr


def test_prefers_the_repos_own_ruff_over_one_on_path(gate, tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "ruff").write_text("", encoding="utf-8")

    assert gate.find_formatter(root) == [str(root / ".venv" / "bin" / "ruff"), "format"]
