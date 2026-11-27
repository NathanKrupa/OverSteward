# ABOUTME: Tests for the dispatch watchdog — the silent-loop guard read from the dispatch worktree.
# ABOUTME: Real git worktrees for the OS#632 fixtures; the remote probe and the clock are injected.

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from oversteward import dispatch_watchdog as wd

POLL = 600.0  # ten minutes between readings, so a 100-minute run is ten polls


def _load_cli():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dispatch" / "dispatch_watchdog.py"
    spec = importlib.util.spec_from_file_location("dispatch_watchdog_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _worktree(tmp_path: Path, issue: int = 7, branch: str = "fix/issue-7-x") -> Path:
    """A dispatch worktree with one commit, at the path the playbook gives it."""
    wt = wd.worktree_path(tmp_path / "checkout", issue)
    wt.mkdir(parents=True)
    _git(wt, "init", "-q", "-b", branch)
    _git(wt, "config", "user.email", "t@example.com")
    _git(wt, "config", "user.name", "T")
    _commit(wt, "first")
    return wt


def _commit(wt: Path, name: str) -> None:
    (wt / f"{name}.txt").write_text(name, encoding="utf-8")
    _git(wt, "add", f"{name}.txt")
    _git(wt, "commit", "-qm", name)


def _touch(path: Path, n: int) -> None:
    """Write ``path`` with an mtime that differs on every call, without waiting."""
    path.write_text(str(n), encoding="utf-8")
    os.utime(path, ns=(n * 10**9, n * 10**9))


def _drive(read, actions, *, warn_min: float = 60.0):
    """Run watch() with a clock that advances one POLL per sleep, doing actions[i] at sleep i."""
    now = [0.0]
    calls = iter(actions)
    progress: list[str] = []

    def sleeper(_seconds: float) -> None:
        now[0] += POLL
        next(calls, lambda: None)()

    verdict = wd.watch(
        read,
        warn_min=warn_min,
        poll_sec=POLL,
        sleeper=sleeper,
        clock=lambda: now[0],
        report=lambda v, m: progress.append(v.reason),
    )
    return verdict, now[0] / 60.0, progress


def _reader(wt: Path, remote=lambda: ""):
    return lambda: wd.read_snapshot(wt, remote)


# --- the OS#632 acceptance fixtures ---------------------------------------


def test_commits_with_no_remote_branch_never_alert_and_the_run_exits_0(tmp_path):
    # Commits every 10 minutes for 100 minutes (past the 60-minute warn), no
    # remote branch ever (the marker pre-push hook holds the push), then teardown.
    wt = _worktree(tmp_path)
    actions = [lambda i=i: _commit(wt, f"c{i}") for i in range(10)]
    actions.append(lambda: shutil.rmtree(wt))

    verdict, elapsed_min, progress = _drive(_reader(wt), actions)

    assert verdict.status == "finished"
    assert wd.exit_code(verdict) == 0
    assert elapsed_min > 60
    assert progress and all(reason == "moved: commit" for reason in progress)


def test_a_worktree_frozen_past_warn_min_exits_3(tmp_path):
    wt = _worktree(tmp_path)
    _commit(wt, "second")

    verdict, elapsed_min, progress = _drive(_reader(wt), [])

    assert verdict.status == "stalled"
    assert wd.exit_code(verdict) == 3
    assert elapsed_min == 60
    assert progress == []
    assert "warn baseline 60m" in verdict.reason


def test_the_idle_clock_restarts_at_the_last_movement(tmp_path):
    # Moves at 10m and 50m, then freezes: the alert comes at 110m, not 60m.
    wt = _worktree(tmp_path)
    actions = [lambda: _commit(wt, "a"), lambda: None, lambda: None, lambda: None,
               lambda: _commit(wt, "b")]

    verdict, elapsed_min, _ = _drive(_reader(wt), actions)

    assert verdict.status == "stalled"
    assert elapsed_min == 110


@pytest.mark.parametrize("signal", [".review-rounds", ".review-verdict-1.md", ".verify-marker"])
def test_a_review_file_or_the_verify_marker_advancing_is_movement(tmp_path, signal):
    # Review and `make verify` commit nothing; their files are the evidence.
    wt = _worktree(tmp_path)
    actions = [lambda i=i: _touch(wt / signal, i + 1) for i in range(10)]
    actions.append(lambda: shutil.rmtree(wt))

    verdict, elapsed_min, progress = _drive(_reader(wt), actions)

    assert verdict.status == "finished"
    assert elapsed_min > 60
    expected = "verify marker" if signal == ".verify-marker" else "review files"
    assert progress and all(reason == f"moved: {expected}" for reason in progress)


def test_a_branch_pinned_outside_the_issue_pattern_is_still_seen(tmp_path):
    # OS#494: the issue pinned feat/x, so the remote never shows *issue-7*.
    wt = _worktree(tmp_path, branch="feat/x")
    actions = [lambda i=i: _commit(wt, f"c{i}") for i in range(8)]
    actions.append(lambda: shutil.rmtree(wt))

    verdict, _, _ = _drive(_reader(wt), actions)

    assert verdict.status == "finished"


def test_a_flapping_remote_probe_is_not_movement(tmp_path):
    # Every other probe fails (None); a failure must carry the last reading.
    wt = _worktree(tmp_path)
    flaps = iter(["abc\trefs/heads/fix/issue-7-x", None] * 20)

    verdict, elapsed_min, progress = _drive(_reader(wt, lambda: next(flaps)), [])

    assert verdict.status == "stalled"
    assert elapsed_min == 60
    assert progress == []


def test_a_remote_probe_that_first_reads_after_failing_is_a_baseline(tmp_path):
    wt = _worktree(tmp_path)
    readings = iter([None, "", "", "", "", "", "", ""])

    verdict, elapsed_min, progress = _drive(_reader(wt, lambda: next(readings)), [])

    assert verdict.status == "stalled"
    assert progress == []


def test_a_pushed_branch_moving_is_movement(tmp_path):
    wt = _worktree(tmp_path)
    pushes = iter(["", "a\trefs/heads/fix/issue-7-x", "b\trefs/heads/fix/issue-7-x"])
    remote = lambda: next(pushes, "b\trefs/heads/fix/issue-7-x")  # noqa: E731

    verdict, elapsed_min, progress = _drive(_reader(wt, remote), [])

    assert progress == ["moved: remote branch", "moved: remote branch"]
    assert verdict.status == "stalled"
    assert elapsed_min == 80


def test_a_worktree_appearing_is_movement_and_never_appearing_stalls(tmp_path):
    wt = wd.worktree_path(tmp_path / "checkout", 7)

    verdict, elapsed_min, _ = _drive(_reader(wt), [])
    assert verdict.status == "stalled"
    assert "no dispatch worktree was ever seen" in verdict.reason

    actions = [lambda: _worktree(tmp_path), lambda: None, lambda: shutil.rmtree(wt)]
    verdict, _, progress = _drive(_reader(wt), actions)
    assert progress[0].startswith("moved: commit")
    assert verdict.status == "finished"


# --- the pure pieces -------------------------------------------------------


def test_assess_truth_table():
    def assess(**kw):
        base = dict(idle_min=0, moved=[], worktree_seen=True, worktree_present=True, warn_min=60)
        return wd.assess_dispatch_progress(**{**base, **kw})

    assert assess(worktree_present=False).status == "finished"
    assert assess(worktree_present=False, moved=["commit"]).status == "finished"
    assert assess(moved=["commit"], idle_min=0).status == "progressing"
    assert assess(idle_min=59.9).status == "watching"
    stalled = assess(idle_min=60)
    assert stalled.status == "stalled" and stalled.should_alert
    assert "no dispatch worktree" not in stalled.reason
    never = assess(idle_min=60, worktree_seen=False, worktree_present=False)
    assert never.status == "stalled" and "no dispatch worktree was ever seen" in never.reason


def test_read_snapshot_reads_each_signal(tmp_path):
    wt = _worktree(tmp_path)
    _touch(wt / ".review-rounds", 5)
    _touch(wt / ".verify-marker", 9)

    snap = wd.read_snapshot(wt, lambda: None)

    assert snap.worktree_present
    assert snap.marks["commit"] == _git(wt, "rev-parse", "HEAD")
    assert snap.marks["review files"] == f".review-rounds@{5 * 10**9}"
    assert snap.marks["verify marker"] == str(9 * 10**9)
    assert snap.marks["remote branch"] is None

    gone = wd.read_snapshot(tmp_path / "absent", lambda: "")
    assert not gone.worktree_present
    assert set(gone.marks.values()) == {""}


@dataclass
class _Result:
    stdout: str
    returncode: int = 0


def test_a_head_git_cannot_read_is_unread_not_absent(tmp_path):
    # A present worktree whose rev-parse fails carries the last commit forward.
    snap = wd.read_snapshot(tmp_path, lambda: "", runner=lambda c, **k: _Result("", 128))

    assert snap.worktree_present
    assert snap.marks["commit"] is None


def test_remote_branches_probes_the_issue_glob_without_a_prompt():
    calls = []

    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Result("abc\trefs/heads/feat/issue-947-foo\n")

    assert wd.remote_branches("NathanKrupa/aigranthelper", 947, runner=runner) == (
        "abc\trefs/heads/feat/issue-947-foo"
    )
    cmd, kwargs = calls[0]
    assert cmd == ["git", "ls-remote", "https://github.com/NathanKrupa/aigranthelper.git",
                   "refs/heads/*issue-947*"]
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_remote_branches_none_is_absent_and_a_failure_is_unread():
    assert wd.remote_branches("o/r", 1, runner=lambda c, **k: _Result("\n")) == ""
    assert wd.remote_branches("o/r", 1, runner=lambda c, **k: _Result("", 128)) is None

    def boom(cmd, **kwargs):
        raise OSError("network down")

    assert wd.remote_branches("o/r", 1, runner=boom) is None


def test_checkout_for_matches_the_registry_repo_url():
    contexts = [
        {"repo": "https://github.com/NathanKrupa/Stocks.git"},
        {"repo": "https://github.com/NathanKrupa/aigranthelper.git", "local_path": "/x/ag"},
        {"repo": "https://github.com/NathanKrupa/OverSteward.git", "local_path": "/x/os"},
    ]
    assert wd.checkout_for("NathanKrupa/oversteward", contexts) == Path("/x/os")
    assert wd.checkout_for("NathanKrupa/aigranthelper", contexts) == Path("/x/ag")
    assert wd.checkout_for("NathanKrupa/Stocks", contexts) is None
    assert wd.checkout_for("NathanKrupa/granthelper", contexts) is None


# --- the CLI ---------------------------------------------------------------


def test_cli_exits_2_when_the_checkout_cannot_be_found(capsys):
    cli = _load_cli()

    assert cli.main(["NathanKrupa/no-such-repo", "1"]) == 2
    err = capsys.readouterr().err
    assert "could not look" in err and "--checkout" in err


def test_cli_finds_a_dispatch_targets_checkout_in_the_real_registry():
    cli = _load_cli()

    assert cli._checkout("NathanKrupa/aigranthelper", None) == Path("/home/natha/aigranthelper")
