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


BLOCK_VERDICT = (
    "```reviewer-verdict\nverdict: BLOCK\nfindings: 1\ntokens: 1\n```\n1. [hole] x — y\n"
)


def _verdict_file(root: Path) -> Path:
    """The previous verdict, inside the reviewed checkout as the assembler requires."""
    path = root / ".review-verdict.md"
    path.write_text(BLOCK_VERDICT, encoding="utf-8")
    return path


def _advance_master(root: Path) -> None:
    """Move the base under the branch: one more commit on master, merged into the branch."""
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "master"], cwd=root, check=True)
    (root / "moved.txt").write_text("the base moved\n", encoding="utf-8")
    subprocess.run(["git", "add", "moved.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base advances"], cwd=root, check=True)
    subprocess.run(["git", "checkout", "-q", branch], cwd=root, check=True)
    subprocess.run(["git", "merge", "-q", "--no-edit", "master"], cwd=root, check=True)


def _re_review(root: Path, out: Path, verdict: Path, *extra: str) -> subprocess.CompletedProcess:
    return _assemble_with(
        root, out, "--since", "master", "--previous-verdict", str(verdict), *extra
    )


class TestTheRoundIsCountedByTheLedgerAndCappedByTheScript:
    """The three-round budget is a refusal at the assembler, on a count silence cannot reset."""

    def test_the_first_assembly_is_round_one_and_writes_the_ledger(
        self, repo_deleting_a_test, tmp_path
    ):
        out = tmp_path / "out.md"

        result = _assemble_with(repo_deleting_a_test, out)

        assert result.returncode == 0, result.stderr
        assert "round: 1 of 3" in out.read_text(encoding="utf-8")
        ledger = (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8")
        assert ledger.startswith("round=1 base=master base_sha=") and ledger.endswith(" since=-\n")

    def test_the_second_assembly_is_round_two_whether_or_not_the_caller_says_so(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")

        silent = _re_review(
            repo_deleting_a_test, tmp_path / "r2.md", _verdict_file(repo_deleting_a_test)
        )

        assert silent.returncode == 0, silent.stderr
        rendered = (tmp_path / "r2.md").read_text(encoding="utf-8")
        assert "round: 2 of 3" in rendered and "since: master" in rendered
        assert "## previous-verdict" in rendered and "1. [hole] x — y" in rendered

    def test_a_second_assembly_without_the_previous_verdict_is_refused(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")

        result = _assemble_with(repo_deleting_a_test, tmp_path / "r2.md", "--since", "master")

        assert result.returncode == 1
        assert "needs --previous-verdict" in result.stderr

    def test_the_fourth_round_is_refused_even_when_round_is_omitted(
        self, repo_deleting_a_test, tmp_path
    ):
        verdict = _verdict_file(repo_deleting_a_test)
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")
        for n in (2, 3):
            r = _re_review(repo_deleting_a_test, tmp_path / f"r{n}.md", verdict)
            assert r.returncode == 0, r.stderr

        fourth = _re_review(repo_deleting_a_test, tmp_path / "r4.md", verdict)

        assert fourth.returncode == 1
        assert "exceeds the 3-round cap" in fourth.stderr
        assert not (tmp_path / "r4.md").exists(), "a refused round writes no input"

    def test_a_declared_round_that_contradicts_the_ledger_is_refused(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")

        result = _assemble_with(repo_deleting_a_test, tmp_path / "again.md", "--round", "1")

        assert result.returncode == 1
        assert "already built" in result.stderr

    def test_a_missing_verdict_file_is_a_gate_refusal_not_a_traceback(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")

        result = _re_review(
            repo_deleting_a_test, tmp_path / "r2.md", repo_deleting_a_test / "nope.md"
        )

        assert result.returncode == 1
        assert "review-input:" in result.stderr and "could not be read" in result.stderr
        assert "Traceback" not in result.stderr

    def test_a_verdict_file_outside_the_checkout_is_refused(self, repo_deleting_a_test, tmp_path):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")
        outside = tmp_path / "elsewhere.md"
        outside.write_text(BLOCK_VERDICT, encoding="utf-8")

        result = _re_review(repo_deleting_a_test, tmp_path / "r2.md", outside)

        assert result.returncode == 1
        assert "must be inside the reviewed checkout" in result.stderr

    def test_a_refused_assembly_leaves_the_ledger_as_it_was(self, repo_deleting_a_test, tmp_path):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")
        before = (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8")

        refused = _assemble_with(repo_deleting_a_test, tmp_path / "r2.md", "--since", "master")

        assert refused.returncode == 1
        assert (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8") == before, (
            "a refusal is not a round"
        )

    def test_an_assembly_that_could_not_look_is_not_a_round(self, repo_deleting_a_test, tmp_path):
        doctrine = repo_deleting_a_test / "CLAUDE.md"
        kept = doctrine.read_text(encoding="utf-8")
        doctrine.unlink()

        blind = _assemble_with(repo_deleting_a_test, tmp_path / "blind.md")
        doctrine.write_text(kept, encoding="utf-8")
        again = _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")

        assert blind.returncode == 2, blind.stderr
        assert again.returncode == 0, again.stderr
        assert "round: 1 of 3" in (tmp_path / "r1.md").read_text(encoding="utf-8"), (
            "an unmeasured assembly did not consume a round"
        )

    def test_a_restart_against_an_unmoved_base_is_refused_and_names_the_escape(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")
        before = (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8")

        result = _assemble_with(
            repo_deleting_a_test, tmp_path / "again.md", "--restart-rounds", "x"
        )

        assert result.returncode == 1
        assert "has not moved" in result.stderr and "--override-cap" in result.stderr
        assert (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8") == before

    def test_a_restart_after_the_base_moved_is_a_printed_round_one_appended_to_the_ledger(
        self, repo_deleting_a_test, tmp_path
    ):
        _assemble_with(repo_deleting_a_test, tmp_path / "r1.md")
        _advance_master(repo_deleting_a_test)

        result = _assemble_with(
            repo_deleting_a_test, tmp_path / "restart.md", "--restart-rounds", "base advanced"
        )

        assert result.returncode == 0, result.stderr
        rendered = (tmp_path / "restart.md").read_text(encoding="utf-8")
        assert "round: 1 of 3" in rendered and "ROUNDS RESTARTED: base advanced" in rendered
        ledger = (repo_deleting_a_test / ".review-rounds").read_text(encoding="utf-8").splitlines()
        assert len(ledger) == 2 and ledger[1].endswith(" since=- restart"), (
            "appended, not truncated"
        )

    def test_an_override_at_round_one_is_refused(self, repo_deleting_a_test, tmp_path):
        result = _assemble_with(
            repo_deleting_a_test, tmp_path / "r1.md", "--override-cap", "no cap in play"
        )

        assert result.returncode == 1
        assert "cap is not in play" in result.stderr
