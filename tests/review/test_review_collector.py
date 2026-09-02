# ABOUTME: Tests for review_collector — the probes that answer None rather than "" when blind.
# ABOUTME: Also pins gaudi resolution to the interpreter's sibling, never a stranger on PATH.

from __future__ import annotations

import json
import subprocess

import pytest

from oversteward.review_collector import ShellCollector, gaudi_binary


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one commit on master and one on a branch."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "master")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (root / "CLAUDE.md").write_text("# doctrine\n", encoding="utf-8")
    (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    (root / "tests").mkdir()
    (root / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "work")
    # master moves on after the branch point. Without a merge-base diff the
    # reviewer would be handed this commit as if the author had written it —
    # the divergence is the whole reason the probe resolves a merge base.
    git("checkout", "-q", "master")
    (root / "moved_on.py").write_text("y = 2\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base moves on")
    git("checkout", "-q", "feature")
    return root


class TestGaudiResolution:
    def test_resolves_the_binary_beside_the_running_interpreter(self, tmp_path):
        bindir = tmp_path / "venv" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        assert gaudi_binary(str(bindir / "python")) == bindir / "gaudi"

    def test_returns_none_when_the_sibling_is_absent_rather_than_reaching_for_path(self, tmp_path):
        bindir = tmp_path / "venv" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "python").write_text("", encoding="utf-8")
        assert gaudi_binary(str(bindir / "python")) is None

    def test_a_venv_whose_python_is_a_symlink_still_finds_its_own_gaudi(self, tmp_path):
        # Every venv's `bin/python` is a symlink to a system interpreter, so
        # resolving the *executable* walks out of the venv into /usr/bin and
        # finds no gaudi at all — silently disabling the input the reviewer
        # relies on. The bin directory is the thing to look in, not wherever
        # the interpreter it points at happens to live.
        system_bin = tmp_path / "usr" / "bin"
        system_bin.mkdir(parents=True)
        (system_bin / "python3.12").write_text("#!/bin/sh\n", encoding="utf-8")
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").symlink_to(system_bin / "python3.12")
        (venv_bin / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        assert gaudi_binary(str(venv_bin / "python")) == venv_bin / "gaudi"

    def test_a_gaudi_elsewhere_on_path_is_never_adopted(self, tmp_path, monkeypatch):
        stranger = tmp_path / "elsewhere"
        stranger.mkdir()
        (stranger / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("PATH", str(stranger))
        bindir = tmp_path / "venv" / "bin"
        bindir.mkdir(parents=True)
        assert gaudi_binary(str(bindir / "python")) is None


class TestDiffProbes:
    def test_the_diff_covers_the_branch_and_not_the_base(self, repo):
        diff = ShellCollector(repo).diff("master")
        assert "tests/test_new.py" in diff
        assert "keep.py" not in diff

    def test_commits_the_base_gained_after_the_branch_point_are_not_shown_as_the_authors(
        self, repo
    ):
        diff = ShellCollector(repo).diff("master")
        assert "moved_on.py" not in diff

    def test_changed_files_lists_the_branch_additions(self, repo):
        assert ShellCollector(repo).changed_files("master") == ["tests/test_new.py"]

    def test_an_unknown_base_ref_answers_none_not_an_empty_diff(self, repo):
        collector = ShellCollector(repo)
        assert collector.diff("origin/no-such-branch") is None
        assert collector.changed_files("origin/no-such-branch") is None


class TestFileProbes:
    def test_reads_a_tracked_file(self, repo):
        assert "def test_new" in ShellCollector(repo).file_text("tests/test_new.py")

    def test_a_deleted_file_answers_none_rather_than_empty(self, repo):
        assert ShellCollector(repo).file_text("tests/gone.py") is None

    def test_claude_md_is_read_from_the_repo_root(self, repo):
        assert ShellCollector(repo).claude_md() == "# doctrine\n"

    def test_a_repo_without_doctrine_answers_none(self, tmp_path):
        assert ShellCollector(tmp_path).claude_md() is None


class TestGaudiProbe:
    def test_absent_gaudi_answers_none_so_the_section_cannot_read_as_clean(self, repo):
        collector = ShellCollector(repo, gaudi=None)
        assert collector.gaudi_json(["keep.py"]) is None

    def test_a_gaudi_that_fails_answers_none_rather_than_a_partial_report(self, repo, tmp_path):
        broken = tmp_path / "broken-gaudi"
        broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        broken.chmod(0o755)
        assert ShellCollector(repo, gaudi=broken).gaudi_json(["keep.py"]) is None

    def test_a_report_is_keyed_by_file_and_ordered_deterministically(self, repo, tmp_path):
        stub = tmp_path / "stub-gaudi"
        stub.write_text('#!/bin/sh\necho \'{"findings": []}\'\n', encoding="utf-8")
        stub.chmod(0o755)
        collector = ShellCollector(repo, gaudi=stub)
        report = collector.gaudi_json(["b.py", "a.py"])
        assert list(json.loads(report)) == ["a.py", "b.py"]
        assert report == collector.gaudi_json(["a.py", "b.py"])

    def test_non_json_output_answers_none_rather_than_being_passed_through(self, repo, tmp_path):
        noisy = tmp_path / "noisy-gaudi"
        noisy.write_text("#!/bin/sh\necho 'usage: gaudi check [OPTIONS]'\n", encoding="utf-8")
        noisy.chmod(0o755)
        assert ShellCollector(repo, gaudi=noisy).gaudi_json(["keep.py"]) is None


class TestIssueProbe:
    def test_a_gh_failure_answers_none(self, repo, monkeypatch):
        monkeypatch.setenv("PATH", "")
        assert ShellCollector(repo).issue_body("NathanKrupa/OverSteward", 428) is None
