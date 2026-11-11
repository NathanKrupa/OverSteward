# ABOUTME: Exercises the check run on a captured review result, against real git worktrees.
# ABOUTME: A result with no verdict fence is a blind round: its scratch copy is recorded, restored, torn down.

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from oversteward.review_capture import (
    EXIT_BLIND,
    EXIT_SECOND_BLIND,
    EXIT_STOP,
    EXIT_VERDICT,
    check_capture,
    run_git,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "review" / "check_verdict_capture.py"

GUARDED = "def billable(price_id, items):\n    return bool(price_id) and any(items)\n"
MUTANT = "def billable(price_id, items):\n    return bool(price_id) or any(items)\n"

#: Verbatim from the AG#2821 blind launch (OS#682).
BLIND_RESULT = (
    "The mutation loop is still running in the background. "
    "I'll pick the results up when it finishes.\n"
)


def _verdict(verdict: str, findings: int) -> str:
    return f"```reviewer-verdict\nverdict: {verdict}\nfindings: {findings}\ntokens: 1200\n```\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def author(tmp_path: Path) -> Path:
    """An author's worktree beside its primary checkout, with a reviewer's scratch copy."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "master")
    _git(primary, "config", "user.email", "t@example.com")
    _git(primary, "config", "user.name", "T")
    (primary / "billing.py").write_text(GUARDED, encoding="utf-8")
    _git(primary, "add", "billing.py")
    _git(primary, "commit", "-qm", "base")
    worktree = tmp_path / "dispatch-1"
    _git(primary, "worktree", "add", "-q", "-b", "feature", str(worktree))
    _git(worktree, "worktree", "add", "-q", "--detach", f"{worktree}.review", "HEAD")
    return worktree


def _scratch(worktree: Path) -> Path:
    return worktree.with_name(f"{worktree.name}.review")


def _leave_a_mutant(worktree: Path) -> None:
    scratch = _scratch(worktree)
    (scratch / "billing.py").write_text(MUTANT, encoding="utf-8")
    (scratch / "mutation_loop.log").write_text("mutant 3 of 9\n", encoding="utf-8")


def _capture(worktree: Path, text: str, name: str = ".review-verdict-1.md") -> Path:
    path = worktree / name
    path.write_text(text, encoding="utf-8")
    return path


def _teardown(code: int = 0) -> Mock:
    return Mock(return_value=code)


def _status(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class TestAVerdictIsAVerdict:
    @pytest.mark.parametrize(
        "verdict, findings", [("PASS", 0), ("PASS-WITH-FINDINGS", 2), ("BLOCK", 1)]
    )
    def test_a_fenced_verdict_exits_zero_and_touches_nothing(
        self, author: Path, verdict: str, findings: int
    ) -> None:
        _leave_a_mutant(author)
        teardown = _teardown()
        outcome = check_capture(
            _capture(author, f"{_verdict(verdict, findings)}\n1. hole: …\n"),
            git=run_git,
            teardown=teardown,
        )
        assert outcome.code == EXIT_VERDICT, outcome.message
        assert verdict in outcome.message
        teardown.assert_not_called()
        assert (_scratch(author) / "billing.py").read_text(encoding="utf-8") == MUTANT

    def test_an_unreadable_fence_stops_without_recovering(self, author: Path) -> None:
        _leave_a_mutant(author)
        teardown = _teardown()
        outcome = check_capture(
            _capture(author, _verdict("PASS", 3)), git=run_git, teardown=teardown
        )
        assert outcome.code == EXIT_STOP
        assert "PASS-WITH-FINDINGS" in outcome.message
        teardown.assert_not_called()


class TestABlindRoundIsRecordedRestoredAndTornDown:
    def test_the_mutant_is_recorded_then_restored_and_the_copy_torn_down(
        self, author: Path
    ) -> None:
        _leave_a_mutant(author)
        teardown = _teardown()
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=teardown)

        assert outcome.code == EXIT_BLIND, outcome.message
        assert "relaunch" in outcome.message
        record = (author / ".review-verdict-1.blind.md").read_text(encoding="utf-8")
        assert BLIND_RESULT.strip() in record
        assert "+    return bool(price_id) or any(items)" in record
        assert "mutation_loop.log" in record
        scratch = _scratch(author)
        assert (scratch / "billing.py").read_text(encoding="utf-8") == GUARDED
        assert not (scratch / "mutation_loop.log").exists()
        assert _status(scratch) == ""
        teardown.assert_called_once_with(scratch, author.parent / "primary")

    def test_a_blind_round_with_no_copy_left_is_still_blind(self, author: Path) -> None:
        _git(author, "worktree", "remove", str(_scratch(author)))
        teardown = _teardown()
        outcome = check_capture(_capture(author, "null\n"), git=run_git, teardown=teardown)
        assert outcome.code == EXIT_BLIND, outcome.message
        teardown.assert_not_called()
        assert "no scratch copy" in (author / ".review-verdict-1.blind.md").read_text(
            encoding="utf-8"
        )

    def test_the_relaunch_coming_back_blind_too_stops_the_pickup(self, author: Path) -> None:
        _leave_a_mutant(author)
        first = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=_teardown())
        assert first.code == EXIT_BLIND
        # The stub doctor removed nothing; the relaunched reviewer's copy is a fresh one.
        _git(author, "worktree", "remove", str(_scratch(author)))
        _git(author, "worktree", "add", "-q", "--detach", str(_scratch(author)), "HEAD")
        _leave_a_mutant(author)
        teardown = _teardown()
        second = check_capture(
            _capture(author, BLIND_RESULT, ".review-verdict-1-relaunch.md"),
            git=run_git,
            teardown=teardown,
        )
        assert second.code == EXIT_SECOND_BLIND, second.message
        assert (author / ".review-verdict-1-relaunch.blind.md").is_file()
        assert (_scratch(author) / "billing.py").read_text(encoding="utf-8") == GUARDED
        teardown.assert_called_once()

    def test_a_blind_round_in_a_later_round_is_counted_on_its_own(self, author: Path) -> None:
        (author / ".review-verdict-1-relaunch.blind.md").write_text("earlier\n", encoding="utf-8")
        _leave_a_mutant(author)
        outcome = check_capture(
            _capture(author, BLIND_RESULT, ".review-verdict-2.md"),
            git=run_git,
            teardown=_teardown(),
        )
        assert outcome.code == EXIT_BLIND, outcome.message
        assert (author / ".review-verdict-2.blind.md").is_file()

    def test_a_doctor_refusal_stops_the_pickup(self, author: Path) -> None:
        _leave_a_mutant(author)
        outcome = check_capture(
            _capture(author, BLIND_RESULT), git=run_git, teardown=_teardown(code=1)
        )
        assert outcome.code == EXIT_STOP
        assert "worktree_doctor" in outcome.message

    def test_a_link_the_reviewer_added_is_removed_and_its_target_kept(
        self, author: Path, tmp_path: Path
    ) -> None:
        kept = tmp_path / "bench-data"
        kept.mkdir()
        (kept / "rows.csv").write_text("1\n", encoding="utf-8")
        (_scratch(author) / "bench").symlink_to(kept, target_is_directory=True)
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=_teardown())
        assert outcome.code == EXIT_BLIND, outcome.message
        assert not (_scratch(author) / "bench").is_symlink()
        assert (kept / "rows.csv").read_text(encoding="utf-8") == "1\n"

    def test_the_authors_own_worktree_is_never_restored(self, author: Path) -> None:
        (author / "billing.py").write_text(MUTANT, encoding="utf-8")
        (author / "draft.py").write_text("WIP = True\n", encoding="utf-8")
        _leave_a_mutant(author)
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=_teardown())
        assert outcome.code == EXIT_BLIND, outcome.message
        assert (author / "billing.py").read_text(encoding="utf-8") == MUTANT
        assert (author / "draft.py").read_text(encoding="utf-8") == "WIP = True\n"

    def test_a_record_that_cannot_be_written_restores_nothing(self, author: Path) -> None:
        _leave_a_mutant(author)
        capture = _capture(author, BLIND_RESULT)
        teardown = _teardown()
        author.chmod(0o555)
        try:
            outcome = check_capture(capture, git=run_git, teardown=teardown)
        finally:
            author.chmod(0o755)
        assert outcome.code == EXIT_STOP
        assert "nothing was restored" in outcome.message
        assert (_scratch(author) / "billing.py").read_text(encoding="utf-8") == MUTANT
        teardown.assert_not_called()

    def test_a_staged_mutant_the_restore_cannot_clear_never_reaches_the_doctor(
        self, author: Path
    ) -> None:
        _leave_a_mutant(author)
        _git(_scratch(author), "add", "billing.py")
        teardown = _teardown()
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=teardown)
        assert outcome.code == EXIT_STOP
        assert "billing.py" in outcome.message
        teardown.assert_not_called()


    def test_a_tracked_file_swapped_for_a_link_never_writes_through_it(
        self, author: Path
    ) -> None:
        """Round-1 finding 1: the restore followed a link into the author's worktree."""
        (author / "billing.py").write_text("AUTHOR UNCOMMITTED WORK\n", encoding="utf-8")
        scratch = _scratch(author)
        (scratch / "billing.py").unlink()
        (scratch / "billing.py").symlink_to(author / "billing.py")
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=_teardown())
        assert outcome.code == EXIT_BLIND, outcome.message
        assert (author / "billing.py").read_text(encoding="utf-8") == "AUTHOR UNCOMMITTED WORK\n"
        assert not (scratch / "billing.py").is_symlink()
        assert (scratch / "billing.py").read_text(encoding="utf-8") == GUARDED

    def test_a_directory_swapped_for_a_link_stops_before_touching_anything(
        self, author: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "billing.py").write_text("OUTSIDE\n", encoding="utf-8")
        (outside / "new.py").write_text("OUTSIDE NEW\n", encoding="utf-8")
        (author / "pkg").mkdir()
        (author / "pkg" / "billing.py").write_text(GUARDED, encoding="utf-8")
        _git(author, "add", "pkg/billing.py")
        _git(author, "commit", "-qm", "a tracked package")
        scratch = _scratch(author)
        _git(author, "worktree", "remove", str(scratch))
        _git(author, "worktree", "add", "-q", "--detach", str(scratch), "HEAD")
        shutil.rmtree(scratch / "pkg")
        (scratch / "pkg").symlink_to(outside, target_is_directory=True)
        teardown = _teardown()
        outcome = check_capture(_capture(author, BLIND_RESULT), git=run_git, teardown=teardown)
        assert outcome.code == EXIT_STOP, outcome.message
        assert "symlinked directory" in outcome.message
        assert (outside / "billing.py").read_text(encoding="utf-8") == "OUTSIDE\n"
        assert (outside / "new.py").read_text(encoding="utf-8") == "OUTSIDE NEW\n"
        teardown.assert_not_called()

    def test_checking_the_same_capture_again_is_not_a_second_blind_round(
        self, author: Path
    ) -> None:
        """Round-1 finding 3: a re-run after a hand repair counted as a second launch."""
        _leave_a_mutant(author)
        capture = _capture(author, BLIND_RESULT)
        first = check_capture(capture, git=run_git, teardown=_teardown(code=1))
        assert first.code == EXIT_STOP
        again = check_capture(capture, git=run_git, teardown=_teardown())
        assert again.code == EXIT_BLIND, again.message
        record = (author / ".review-verdict-1.blind.md").read_text(encoding="utf-8")
        assert "+    return bool(price_id) or any(items)" in record
        assert "# Checked again" in record
        assert not (author / ".review-verdict-1-relaunch.blind.md").exists()


class TestWhatCannotBeCheckedStops:
    def test_a_capture_that_cannot_be_read_stops(self, author: Path) -> None:
        teardown = _teardown()
        outcome = check_capture(author / ".review-verdict-1.md", git=run_git, teardown=teardown)
        assert outcome.code == EXIT_STOP
        teardown.assert_not_called()

    def test_a_file_not_named_as_a_capture_stops(self, author: Path) -> None:
        _leave_a_mutant(author)
        teardown = _teardown()
        outcome = check_capture(
            _capture(author, BLIND_RESULT, "verdict.md"), git=run_git, teardown=teardown
        )
        assert outcome.code == EXIT_STOP
        assert ".review-verdict-<N>" in outcome.message
        teardown.assert_not_called()


    def test_a_scratch_copy_git_cannot_read_stops_and_says_so(self, author: Path) -> None:
        """Round-1 finding 4: an unreadable copy was recorded as no copy at all."""
        _git(author, "worktree", "remove", str(_scratch(author)))
        _scratch(author).mkdir()
        (_scratch(author) / "billing.py").write_text(MUTANT, encoding="utf-8")
        teardown = _teardown()
        outcome = check_capture(
            _capture(author, BLIND_RESULT), git=run_git, teardown=teardown
        )
        assert outcome.code == EXIT_STOP
        assert "could not read the state" in outcome.message
        teardown.assert_not_called()

    def test_a_copy_whose_primary_cannot_be_named_never_reaches_the_doctor(
        self, author: Path
    ) -> None:
        def no_worktree_list(args: list[str]) -> subprocess.CompletedProcess[bytes]:
            if "worktree" in args:
                return subprocess.CompletedProcess(args, 128, b"", b"fatal")
            return run_git(args)

        _leave_a_mutant(author)
        teardown = _teardown()
        outcome = check_capture(
            _capture(author, BLIND_RESULT), git=no_worktree_list, teardown=teardown
        )
        assert outcome.code == EXIT_STOP
        assert "primary checkout" in outcome.message
        teardown.assert_not_called()

    def test_an_absent_git_is_a_failed_call_not_a_traceback(self) -> None:
        result = run_git(["status"], executable="git-that-is-not-installed")
        assert result.returncode != 0
        assert b"git-that-is-not-installed" in result.stderr

    def test_a_verdict_with_a_stray_byte_is_still_read(self, author: Path) -> None:
        """Round-1 finding 2: a non-UTF-8 byte crashed the read."""
        capture = author / ".review-verdict-1.md"
        capture.write_bytes(_verdict("PASS", 0).encode() + b"\xff\n")
        outcome = check_capture(capture, git=run_git, teardown=_teardown())
        assert outcome.code == EXIT_VERDICT, outcome.message


def _script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


class TestTheScript:
    def test_a_verdict_exits_zero(self, author: Path) -> None:
        proc = _script(str(_capture(author, _verdict("PASS", 0))))
        assert proc.returncode == EXIT_VERDICT, proc.stderr
        assert "PASS" in proc.stdout

    def test_a_missing_capture_is_a_stop_not_a_traceback(self, author: Path) -> None:
        proc = _script(str(author / ".review-verdict-1.md"))
        assert proc.returncode == EXIT_STOP
        assert "STOP" in proc.stderr
        assert "Traceback" not in proc.stderr

    def test_no_outcome_shares_the_exit_status_of_a_crash(self) -> None:
        """Round-1 finding 2: a crash exited 1, which was the code for "relaunch"."""
        crash = subprocess.run(
            [sys.executable, "-c", "raise RuntimeError('crash')"], capture_output=True, check=False
        ).returncode
        assert crash not in (EXIT_VERDICT, EXIT_BLIND, EXIT_SECOND_BLIND, EXIT_STOP)

    def test_a_blind_round_with_no_copy_left_exits_blind(self, author: Path) -> None:
        _git(author, "worktree", "remove", str(_scratch(author)))
        proc = _script(str(_capture(author, BLIND_RESULT)))
        assert proc.returncode == EXIT_BLIND, proc.stderr
        assert "BLIND ROUND" in proc.stderr
