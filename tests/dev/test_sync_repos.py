# ABOUTME: Tests for sync_repos — the dev-machine git-currency sync.
# ABOUTME: Pure plan_sync truth table + count parsing + gather_state/apply_plan with injected runner.

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path


def _load():
    rel = Path("scripts") / "dev" / "sync_repos.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("sync_repos", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


sr = _load()


def _state(**kw):
    base = dict(
        repo_id="r",
        present=True,
        shallow=False,
        current_branch="main",
        target_branch="main",
        ahead=0,
        behind=0,
        dirty=0,
        unpushed=0,
    )
    base.update(kw)
    return sr.RepoState(**base)


# --- plan_sync: the truth table ------------------------------------------


def test_absent_checkout():
    assert sr.plan_sync(_state(present=False)).action == "absent"


def test_no_target_branch_skips():
    assert sr.plan_sync(_state(target_branch="")).action == "skip"


def test_dirty_tree_skips_untouched():
    p = sr.plan_sync(_state(dirty=3))
    assert p.action == "skip" and "uncommitted" in p.reason


def test_feature_branch_skips():
    p = sr.plan_sync(_state(current_branch="feat/x", target_branch="main"))
    assert p.action == "skip" and "feat/x" in p.reason


def test_shallow_clean_on_target_unshallows():
    # shallow counts can't be trusted; behind=0 here is irrelevant.
    p = sr.plan_sync(_state(shallow=True, behind=0))
    assert p.action == "unshallow_ff"


def test_local_commits_ahead_skips_manual():
    """Ahead *and* unpushed — the commits exist nowhere else, so a human decides."""
    p = sr.plan_sync(_state(ahead=2, unpushed=2))
    assert p.action == "skip" and "unpushed" in p.reason


def test_behind_fast_forwards():
    p = sr.plan_sync(_state(behind=7))
    assert p.action == "ff" and "7 behind" in p.reason


def test_zero_zero_is_current():
    assert sr.plan_sync(_state()).action == "current"


def test_dirty_takes_priority_over_shallow():
    # A dirty shallow repo is left fully untouched, not unshallowed.
    assert sr.plan_sync(_state(shallow=True, dirty=1)).action == "skip"


# --- _parse_counts --------------------------------------------------------


def test_parse_counts_normal():
    assert sr._parse_counts("3\t7\n") == (3, 7)


def test_parse_counts_malformed_is_zeroes():
    assert sr._parse_counts("") == (0, 0)
    assert sr._parse_counts("nope") == (0, 0)


# --- gather_state with injected runner ------------------------------------


@dataclass
class _R:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def test_gather_state_absent_when_no_git(tmp_path):
    st = sr.gather_state("r", str(tmp_path))
    assert st.present is False


def test_gather_state_parses_full_clone(tmp_path):
    (tmp_path / ".git").mkdir()

    def runner(cmd, **kw):
        a = cmd[3:]  # after ["git","-C",path]
        if a[:2] == ["rev-parse", "--is-shallow-repository"]:
            return _R(stdout="false\n")
        if a[:2] == ["rev-parse", "--abbrev-ref"]:
            return _R(stdout="staging\n")
        if a[0] == "symbolic-ref":
            return _R(stdout="origin/staging\n")
        if a[0] == "remote" or a[0] == "fetch":
            return _R()
        if a[0] == "status":
            return _R(stdout=" M file.py\n?? new.txt\n")
        if a[0] == "rev-list":
            # ``--count <branch> --not --remotes`` is the unpushed probe;
            # ``--left-right --count`` is the ahead/behind pair.
            if "--not" in a:
                return _R(stdout="0\n")
            return _R(stdout="0\t4\n")
        return _R()

    st = sr.gather_state("gs", str(tmp_path), runner=runner)
    assert st.present and not st.shallow
    assert st.current_branch == "staging" and st.target_branch == "staging"
    assert st.on_target is True
    assert st.ahead == 0 and st.behind == 4
    assert st.dirty == 2



def _recording_runner(calls):
    """Record every git argv and answer with a benign success."""

    def runner(cmd, **kw):
        calls.append(list(cmd))
        return _R()

    return runner

# --- apply_plan with injected runner --------------------------------------


def test_apply_ff_merges_ff_only():
    calls = []
    runner = _recording_runner(calls)
    changed, note = sr.apply_plan(
        sr.SyncPlan("r", "ff", "4 behind"), "/p", runner=runner, target_branch="main"
    )
    assert changed is True
    assert ["git", "-C", "/p", "merge", "--ff-only", "origin/main"] in calls


def test_apply_unshallow_ff_runs_unshallow_then_merge():
    calls = []
    runner = _recording_runner(calls)
    sr.apply_plan(
        sr.SyncPlan("r", "unshallow_ff", "shallow"), "/p", runner=runner, target_branch="main"
    )
    assert ["git", "-C", "/p", "fetch", "--unshallow"] in calls
    assert ["git", "-C", "/p", "merge", "--ff-only", "origin/main"] in calls


def test_apply_skip_is_noop():
    calls = []
    changed, _ = sr.apply_plan(
        sr.SyncPlan("r", "skip", "dirty"),
        "/p",
        runner=lambda c, **k: calls.append(c),
        target_branch="main",
    )
    assert changed is False and calls == []


def test_apply_ff_reports_failure_on_nonzero_merge():
    def runner(cmd, **kw):
        if cmd[3] == "merge":
            return _R(returncode=1, stderr="fatal: Not possible to fast-forward\n")
        return _R()

    changed, note = sr.apply_plan(
        sr.SyncPlan("r", "ff", "x"), "/p", runner=runner, target_branch="main"
    )
    assert changed is False and "ff-only merge failed" in note


# --- lossless strand repair (the 2026-08-11 grantspider incident) ---------
#
# ``git pull --ff-only origin <other-branch>`` fast-forwards whatever branch is
# checked out, so a hygiene pull run against the wrong ref moves a trunk branch
# onto a foreign tip. It reads as "ahead" of its own remote, but every commit it
# gained is already published on some other remote ref — so resetting back loses
# nothing. That is the case the tool must repair by itself; only genuinely
# unpushed work earns a human.


def test_diverged_but_fully_pushed_resets():
    """Ahead of origin, yet nothing unique — provably lossless, so repair it."""
    p = sr.plan_sync(_state(ahead=11, unpushed=0))
    assert p.action == "reset"
    assert "no unpushed" in p.reason


def test_diverged_with_unpushed_work_skips():
    """Real local commits exist nowhere else — never destroy them."""
    p = sr.plan_sync(_state(ahead=3, unpushed=3))
    assert p.action == "skip"
    assert "unpushed" in p.reason


def test_dirty_tree_beats_lossless_reset():
    """A reset would discard uncommitted work the unpushed count cannot see."""
    assert sr.plan_sync(_state(ahead=11, unpushed=0, dirty=1)).action == "skip"


def test_apply_reset_hard_resets_to_target():
    calls = []
    runner = _recording_runner(calls)
    changed, note = sr.apply_plan(
        sr.SyncPlan("r", "reset", "diverged, no unpushed commits"),
        "/repo",
        runner=runner,
        target_branch="main",
    )
    assert changed is True
    assert ["git", "-C", "/repo", "reset", "--hard", "origin/main"] in calls


# --- _fast_forward acts on the branch it was given -----------------------
#
# It used to re-read ``origin/HEAD`` itself, so it could act on a branch that
# ``plan_sync`` never validated — the same wrong-ref shape as the incident.


def test_fast_forward_uses_given_branch_not_origin_head():
    calls = []
    runner = _recording_runner(calls)
    sr.apply_plan(sr.SyncPlan("r", "ff", "2 behind"), "/repo", runner=runner, target_branch="main")
    assert not any("symbolic-ref" in c for call in calls for c in call), (
        "must not re-resolve origin/HEAD; act on the validated branch"
    )
    assert ["git", "-C", "/repo", "merge", "--ff-only", "origin/main"] in calls


def test_fast_forward_never_uses_git_pull():
    """``git pull <remote> <ref>`` is the shape that caused the incident."""
    calls = []
    runner = _recording_runner(calls)
    sr.apply_plan(sr.SyncPlan("r", "ff", "2 behind"), "/repo", runner=runner, target_branch="main")
    assert not any("pull" in call for call in calls)
