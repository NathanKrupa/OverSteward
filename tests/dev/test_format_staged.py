# ABOUTME: Tests the canonical pre-commit gate (shared/scripts/dev/format_staged.py).
# ABOUTME: A blocked commit here is what stops formatter residue existing at verify time (OS#78).

from __future__ import annotations

import pytest

from tests.dev.conftest import (
    FORMATTED,
    UNFORMATTED,
    Repo,
    StandInFormatter,
    load_dev_script,
    run_gate,
)

SCRIPT = "format_staged.py"

OK = 0
REFORMATTED = 1
UNUSABLE = 2


@pytest.fixture(scope="module")
def gate():
    return load_dev_script(SCRIPT)


def _run(repo: Repo, formatter: StandInFormatter, *args: str):
    return run_gate(SCRIPT, repo, "--formatter", formatter.command, *args)


def test_blocks_the_commit_when_a_staged_file_is_reformatted(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.stage("app.py")

    result = _run(repo, formatter)

    assert result.returncode == REFORMATTED
    assert "app.py" in result.stderr
    assert "git add" in result.stderr


def test_applies_the_formatting_it_blocks_on(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.stage("app.py")

    _run(repo, formatter)

    assert repo.read("app.py") == FORMATTED


def test_passes_when_staged_python_is_already_formatted(repo, formatter):
    repo.write("app.py", FORMATTED)
    repo.stage("app.py")

    result = _run(repo, formatter)

    assert result.returncode == OK
    assert result.stderr == ""


def test_ignores_staged_files_that_are_not_python(repo, formatter):
    repo.write("notes.md", UNFORMATTED)
    repo.stage("notes.md")

    result = _run(repo, formatter)

    assert result.returncode == OK
    assert formatter.calls == []
    assert repo.read("notes.md") == UNFORMATTED


def test_leaves_unstaged_python_untouched(repo, formatter):
    repo.write("staged.py", UNFORMATTED)
    repo.stage("staged.py")
    repo.write("unstaged.py", UNFORMATTED)

    _run(repo, formatter)

    assert formatter.formatted_paths == {"staged.py"}
    assert repo.read("unstaged.py") == UNFORMATTED


def test_ignores_a_staged_deletion(repo, formatter):
    repo.write("gone.py", FORMATTED)
    repo.commit_all()
    (repo.root / "gone.py").unlink()
    repo.stage("gone.py")

    result = _run(repo, formatter)

    assert result.returncode == OK
    assert formatter.calls == []


def test_exits_unusable_when_no_formatter_is_available(repo, formatter):
    repo.write("app.py", UNFORMATTED)
    repo.stage("app.py")

    result = run_gate(SCRIPT, repo, "--formatter", "")

    assert result.returncode == UNUSABLE
    assert "no formatter found" in result.stderr


def test_excludes_the_canonical_family_from_the_repos_own_formatter(gate, tmp_path):
    """--force-exclude is what keeps a passed-by-name family member unformatted (OS#241)."""
    root = tmp_path / "repo"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "ruff").write_text("", encoding="utf-8")

    assert gate.find_formatter(root)[1:] == ["format", "--force-exclude"]
