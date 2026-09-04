# ABOUTME: End-to-end assembly over a real git repo whose branch deletes a test module.
# ABOUTME: Proves the deleted content reaches the document, and that blindness still exits 2.

"""The flagship case, run through the shipped script rather than a stub.

The unit tests state what the assembler does with a scripted collector; these
state what happens when git, gaudi and the CLI are the real ones. Both halves
are needed: a stub can be taught anything, and a script can diverge from the
service it wraps.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from oversteward.review_input import COULD_NOT_LOOK, EXIT_COULD_NOT_LOOK, EXIT_OK

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "review" / "assemble_review_input.py"

DELETED_TEST_BODY = "test_a_blocked_url_never_reaches_httpx"


def _assemble(root: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--base",
            "master",
            "--no-issue",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class TestADeletingDiffAssemblesMeasured:
    def test_the_assembler_exits_zero_and_renders_the_deleted_test(
        self, repo_deleting_a_test, tmp_path
    ):
        out = tmp_path / "review-input.md"
        proc = _assemble(repo_deleting_a_test, out)
        document = out.read_text(encoding="utf-8")
        assert proc.returncode == EXIT_OK, proc.stderr
        assert DELETED_TEST_BODY in document
        assert "DELETED BY THIS DIFF" in document
        assert COULD_NOT_LOOK not in document

    def test_the_surviving_python_file_is_linted_and_the_deleted_one_named_as_skipped(
        self, repo_deleting_a_test, tmp_path
    ):
        out = tmp_path / "review-input.md"
        _assemble(repo_deleting_a_test, out)
        document = out.read_text(encoding="utf-8")
        assert "safe_http.py" in document
        assert "Skipped by design" in document


class TestBlindnessStillReadsAsBlindness:
    """The deleted-file fix must not turn every missing input into a measured one."""

    def test_a_changed_test_missing_for_no_stated_reason_is_could_not_look(
        self, repo_deleting_a_test, tmp_path
    ):
        # Added on the branch, then removed from the working tree without
        # being committed: the diff does not delete it, so nothing can say
        # where it went. That is the shape a too-eager fix would paper over.
        added = repo_deleting_a_test / "tests" / "test_added_then_vanished.py"
        added.parent.mkdir(exist_ok=True)
        added.write_text("def test_added():\n    assert True\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo_deleting_a_test), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_deleting_a_test), "commit", "-qm", "add a test"],
            check=True,
            capture_output=True,
        )
        added.unlink()

        out = tmp_path / "review-input.md"
        proc = _assemble(repo_deleting_a_test, out)
        document = out.read_text(encoding="utf-8")
        assert proc.returncode == EXIT_COULD_NOT_LOOK, proc.stderr
        assert "UNMEASURED INPUTS: changed-test-files" in document
        assert COULD_NOT_LOOK in document
        assert "UNMEASURED: changed-test-files" in proc.stderr

    def test_a_repo_without_doctrine_is_unmeasured_while_the_deletion_stays_measured(
        self, repo_deleting_a_test, tmp_path
    ):
        (repo_deleting_a_test / "CLAUDE.md").unlink()
        out = tmp_path / "review-input.md"
        proc = _assemble(repo_deleting_a_test, out)
        assert proc.returncode == EXIT_COULD_NOT_LOOK, proc.stderr
        document = out.read_text(encoding="utf-8")
        header = next(
            line for line in document.splitlines() if line.startswith("UNMEASURED INPUTS:")
        )
        assert "repo-doctrine" in header
        # The same document measures the deleted test: one blind probe must not
        # be reported as blindness everywhere, nor the reverse.
        assert "changed-test-files" not in header
        assert DELETED_TEST_BODY in document


def _assemble_with(root: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--base",
            "master",
            "--no-issue",
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheRoundCapIsEnforcedByTheScript:
    """The three-round budget is a refusal at the assembler, not a sentence in the brief."""

    def test_a_fourth_round_is_refused_with_a_usage_exit(self, repo_deleting_a_test, tmp_path):
        verdict = tmp_path / "verdict.md"
        verdict.write_text("verdict: BLOCK\nfindings: 1\n", encoding="utf-8")

        result = _assemble_with(
            repo_deleting_a_test,
            tmp_path / "out.md",
            "--round",
            "4",
            "--previous-verdict",
            str(verdict),
        )

        assert result.returncode == 1, result.stderr
        assert "exceeds the 3-round cap" in result.stderr
        assert not (tmp_path / "out.md").exists(), "a refused round writes no input"

    def test_a_re_review_on_the_delta_names_its_round_and_carries_the_previous_verdict(
        self, repo_deleting_a_test, tmp_path
    ):
        verdict = tmp_path / "verdict.md"
        verdict.write_text("verdict: BLOCK\nfindings: 1\n1. [hole] x — y\n", encoding="utf-8")
        out = tmp_path / "out.md"

        result = _assemble_with(
            repo_deleting_a_test,
            out,
            "--round",
            "2",
            "--since",
            "master",
            "--previous-verdict",
            str(verdict),
        )

        assert result.returncode == 0, result.stderr
        rendered = out.read_text(encoding="utf-8")
        assert "round: 2 of 3" in rendered
        assert "since: master" in rendered
        assert "## previous-verdict" in rendered and "1. [hole] x — y" in rendered
