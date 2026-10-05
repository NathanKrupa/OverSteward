# ABOUTME: Tests for review_collector — the probes that answer None rather than "" when blind.
# ABOUTME: Also pins gaudi resolution to the interpreter's sibling, never a stranger on PATH.

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from oversteward.review_collector import ShellCollector, gaudi_binary
from oversteward.review_input import GAUDI_SECTION, assemble

#: Python 3.14's parenthesis-free multi-except (PEP 758) — the AG PR #2335 shape.
PEP758_SOURCE = (
    "def to_cents(value):\n"
    "    try:\n"
    "        return int(value)\n"
    "    except ValueError, TypeError:\n"
    "        return 0\n"
)


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


def _stub_gaudi(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!/bin/sh\necho '{{\"marker\": \"{marker}\", \"skipped\": []}}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


class TestTheReviewedRepoPinsItsOwnGaudi:
    """The gaudi that reads a repo's files is the one that repo pins (OS#552).

    The assembler runs under OverSteward's interpreter (Python 3.12), so the
    gaudi beside it cannot parse AG's Python 3.14 sources; AG's own venv gaudi
    can. The reviewed checkout's `.venv` comes first.
    """

    def test_the_checkouts_own_venv_gaudi_is_the_one_that_runs(self, repo):
        _stub_gaudi(repo / ".venv" / "bin" / "gaudi", "repo-pinned")
        report = json.loads(ShellCollector(repo).gaudi_json(["keep.py"]))
        assert report["keep.py"]["marker"] == "repo-pinned"


@pytest.mark.skipif(gaudi_binary() is None, reason="no gaudi beside this interpreter")
@pytest.mark.skipif(sys.version_info >= (3, 14), reason="this gaudi can parse PEP 758")
class TestAnOldGaudiThatCannotParseAFileIsUnmeasured:
    """The real gaudi, on a Python that predates PEP 758, against a real file."""

    def test_the_unparseable_file_is_named_and_the_gate_unmeasured(self, repo):
        (repo / "money.py").write_text(PEP758_SOURCE, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "money.py"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-qm", "pep758"], check=True, capture_output=True
        )
        collector = ShellCollector(repo, gaudi=gaudi_binary())
        result = assemble(collector, repo="o/r", base="master", issue=None, no_issue=True)
        section = next(s for s in result.sections if s.name == GAUDI_SECTION)
        assert not section.measured
        assert "money.py" in section.reason
        assert "parenthesized" in section.reason


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

    def test_a_gaudi_that_prints_a_clean_report_and_still_fails_answers_none(self, repo, tmp_path):
        # The failing stub above prints nothing, so it would pass even if the
        # returncode were ignored entirely — the empty stdout is doing the
        # work. Only a stub that emits a *valid, clean-looking* report and
        # then exits nonzero proves the filter is the exit status.
        lying = tmp_path / "lying-gaudi"
        lying.write_text('#!/bin/sh\necho \'{"findings": []}\'\nexit 3\n', encoding="utf-8")
        lying.chmod(0o755)
        assert ShellCollector(repo, gaudi=lying).gaudi_json(["keep.py"]) is None

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


class TestDeletionProbes:
    def test_the_paths_the_branch_deleted_are_listed(self, repo_deleting_a_test):
        collector = ShellCollector(repo_deleting_a_test)
        assert collector.deleted_files("master") == ["tests/test_safe_http.py"]

    def test_a_modified_file_is_not_reported_as_deleted(self, repo_deleting_a_test):
        assert "safe_http.py" not in ShellCollector(repo_deleting_a_test).deleted_files("master")

    def test_a_branch_deleting_nothing_answers_an_empty_list_not_none(self, repo):
        assert ShellCollector(repo).deleted_files("master") == []

    def test_an_unknown_base_ref_answers_none_rather_than_no_deletions(self, repo):
        assert ShellCollector(repo).deleted_files("origin/no-such-branch") is None

    def test_a_deleted_file_is_still_readable_at_the_base(self, repo_deleting_a_test):
        collector = ShellCollector(repo_deleting_a_test)
        assert collector.file_text("tests/test_safe_http.py") is None
        base_text = collector.file_text_at_base("master", "tests/test_safe_http.py")
        assert "test_a_blocked_url_never_reaches_httpx" in base_text

    def test_a_path_that_never_existed_answers_none_at_the_base_too(self, repo_deleting_a_test):
        collector = ShellCollector(repo_deleting_a_test)
        assert collector.file_text_at_base("master", "tests/test_invented.py") is None

    def test_an_unknown_base_ref_cannot_produce_a_base_version(self, repo_deleting_a_test):
        collector = ShellCollector(repo_deleting_a_test)
        assert collector.file_text_at_base("origin/nope", "tests/test_safe_http.py") is None


class TestIssueProbe:
    def test_a_gh_failure_answers_none(self, repo, monkeypatch):
        monkeypatch.setenv("PATH", "")
        assert ShellCollector(repo).issue_body("NathanKrupa/OverSteward", 428) is None
