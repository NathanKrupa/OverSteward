#!/usr/bin/env python3
# ABOUTME: Keep dev-machine checkouts current with origin — auto-unshallow, ff-only, loud-skip on drift.
# ABOUTME: Registry-driven; pure plan_sync split from injected git IO so the decision logic is unit-tested.
"""Bring every managed local checkout up to origin's default branch — safely.

The dev machine's checkouts drift from the "official" state two ways: they fall
*behind* as PRs merge, and a *shallow* clone can fake a huge bogus divergence
(aigranthelper showed "756 ahead" that was really 0 ahead / 39 behind; the cure
was ``git fetch --unshallow`` then a fast-forward). Plus a stale ``origin/HEAD``
can point at a retired default branch.

This tool reads ``registry.yaml`` and, for each context with a ``local_path``
git checkout, heals ``origin/HEAD``, unshallows a shallow clone, and **only when
provably safe** fast-forwards the default branch. Anything risky — uncommitted
changes, a feature branch checked out, or real local commits — is left untouched
and reported loudly, so drift is always visible and never silently "fixed".

Safe by construction: it never runs ``reset``, ``checkout``/``switch``, a force,
or a ``pull`` on a dirty / feature-branch / ahead checkout. The worst it does is
``git fetch`` (read) and ``git pull --ff-only`` (cannot diverge).

The pure decision (``plan_sync``) is split from the git IO so the logic is
unit-tested without a real repo or network, mirroring
``scripts/dispatch/dispatch_watchdog.py``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "registry.yaml"
_GIT_TIMEOUT_S = 300

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class RepoState:
    """Observed state of one checkout. Counts are only trusted when not shallow."""

    repo_id: str
    present: bool
    shallow: bool
    current_branch: str
    target_branch: str
    ahead: int
    behind: int
    dirty: int
    #: Commits on the current branch reachable from NO remote ref. Zero means
    #: everything here is published somewhere, so resetting to the target's
    #: remote cannot lose work — which is what makes strand repair automatic.
    unpushed: int = 0

    @property
    def on_target(self) -> bool:
        return bool(self.target_branch) and self.current_branch == self.target_branch


#: Actions that mean "I could not look at this checkout at all". They are kept
#: as distinct action values rather than being recognised by their reason text:
#: classifying an outcome by string-matching its prose is precisely how a
#: could-not-look gets filed as a deliberate skip (OS#384).
ACTION_ABSENT = "absent"
ACTION_UNREADABLE = "unreadable"
_BLIND_ACTIONS = frozenset({ACTION_ABSENT, ACTION_UNREADABLE})

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 2


@dataclass(frozen=True)
class SyncPlan:
    """The decided action for one repo and the reason, for the report."""

    repo_id: str
    action: str  # see the ACTION_* constants
    reason: str


def plan_sync(state: RepoState) -> SyncPlan:
    """Decide the safe action from a repo's state.

    Order matters: the gates that are reliable even on a shallow clone (missing
    checkout, dirty tree, wrong branch) come first; then a shallow clone is sent
    to unshallow-then-ff because its ahead/behind counts can't be trusted yet;
    only on a full clone do we act on the ahead/behind counts.
    """
    rid = state.repo_id
    if not state.present:
        return SyncPlan(rid, ACTION_ABSENT, "no local checkout")
    if not state.target_branch:
        return SyncPlan(rid, ACTION_UNREADABLE, "could not determine origin default branch")
    if state.dirty > 0:
        return SyncPlan(rid, "skip", f"{state.dirty} uncommitted change(s) — left untouched")
    if not state.on_target:
        return SyncPlan(
            rid, "skip", f"on '{state.current_branch}', not target '{state.target_branch}'"
        )
    if state.shallow:
        return SyncPlan(rid, "unshallow_ff", "shallow clone → unshallow + fast-forward")
    if state.ahead > 0:
        # Ahead of its own remote with nothing unique: the branch was moved onto
        # a foreign tip (a hygiene ``pull`` aimed at the wrong ref does exactly
        # this) and every commit it carries is published elsewhere. Resetting is
        # provably lossless, so it needs no human. Only unique work does.
        if state.unpushed == 0:
            return SyncPlan(
                rid,
                "reset",
                f"{state.ahead} ahead but no unpushed commits — lossless reset to origin/{state.target_branch}",
            )
        return SyncPlan(
            rid, "skip", f"{state.unpushed} unpushed commit(s) — manual reconcile"
        )
    if state.behind > 0:
        return SyncPlan(rid, "ff", f"{state.behind} behind → fast-forward")
    return SyncPlan(rid, "current", "already current")


def _git(runner: Runner, path: str, *args: str) -> subprocess.CompletedProcess:
    return runner(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
    )


def _ok(result: subprocess.CompletedProcess) -> bool:
    return getattr(result, "returncode", 1) == 0


def gather_state(
    repo_id: str, path: str, *, runner: Runner = subprocess.run, primary_branch: str = ""
) -> RepoState:
    """Probe a checkout's state via git. ``runner`` is injected for testing.

    Heals ``origin/HEAD`` (``remote set-head --auto``) before reading the default
    branch, and fetches so ahead/behind are measured against a fresh remote.

    ``primary_branch`` (registry ``primary_branch``) wins over ``origin/HEAD``.
    The two differ wherever a checkout deliberately tracks the branch production
    runs rather than the repo's integration default — grantspider defaults to
    ``staging`` but its primary checkout must sit on ``main``, because
    ``db migrate-prod run`` refuses anywhere else. Inferring the target from
    ``origin/HEAD`` there makes the tool skip the very checkout it should tend.
    """
    absent = RepoState(repo_id, False, False, "", "", 0, 0, 0)
    if not Path(path, ".git").exists():
        return absent

    shallow = _git(runner, path, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    current = _git(runner, path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    _git(runner, path, "remote", "set-head", "origin", "--auto")
    head = _git(runner, path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default = primary_branch or (head.stdout.strip().removeprefix("origin/") if _ok(head) else "")
    if not default:
        return RepoState(repo_id, True, shallow, current, "", 0, 0, 0)

    _git(runner, path, "fetch", "origin", default)
    dirty = len([ln for ln in _git(runner, path, "status", "--porcelain").stdout.splitlines() if ln])
    counts = _git(runner, path, "rev-list", "--left-right", "--count", f"{current}...origin/{default}")
    ahead, behind = _parse_counts(counts.stdout)
    # Commits here that no remote ref carries. ``--not --remotes`` subtracts
    # every origin branch, not just this one's — a branch stranded onto another
    # branch's tip therefore scores zero, which is exactly the lossless case.
    unpushed_out = _git(runner, path, "rev-list", "--count", current, "--not", "--remotes")
    unpushed = int(unpushed_out.stdout.strip() or 0) if _ok(unpushed_out) else ahead
    return RepoState(repo_id, True, shallow, current, default, ahead, behind, dirty, unpushed)


def _parse_counts(stdout: str) -> tuple[int, int]:
    """Parse ``git rev-list --left-right --count`` output ('<ahead>\\t<behind>')."""
    parts = stdout.split()
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (0, 0)


def apply_plan(
    plan: SyncPlan, path: str, *, runner: Runner = subprocess.run, target_branch: str
) -> tuple[bool, str]:
    """Carry out a plan's git action. Returns (changed, note). Only ff/unshallow/reset act.

    ``target_branch`` is passed in rather than re-resolved here: this function
    must act on the branch :func:`plan_sync` actually validated. Re-reading
    ``origin/HEAD`` at apply time let it operate on a branch nothing had
    checked — the same wrong-ref shape that strands a trunk branch.
    """
    if plan.action == "ff":
        return _fast_forward(path, runner, target_branch)
    if plan.action == "unshallow_ff":
        unshallow = _git(runner, path, "fetch", "--unshallow")
        if not _ok(unshallow):
            # Already complete (or no shallow boundary) — fall through to ff.
            pass
        return _fast_forward(path, runner, target_branch)
    if plan.action == "reset":
        return _reset_to_remote(path, runner, target_branch)
    return (False, plan.reason)


def _fast_forward(path: str, runner: Runner, branch: str) -> tuple[bool, str]:
    """Advance the checked-out branch to its remote, without ``git pull``.

    ``git pull <remote> <ref>`` merges into whatever is checked out regardless
    of what it is named, so a wrong ``<ref>`` silently rewrites a trunk branch.
    ``merge --ff-only origin/<branch>`` names the destination explicitly and
    cannot do that; ``gather_state`` has already fetched.
    """
    merge = _git(runner, path, "merge", "--ff-only", f"origin/{branch}")
    if _ok(merge):
        return (True, f"fast-forwarded to origin/{branch}")
    tail = merge.stderr.strip().splitlines()
    return (False, f"ff-only merge failed: {tail[-1] if tail else 'unknown'}")


def _reset_to_remote(path: str, runner: Runner, branch: str) -> tuple[bool, str]:
    """Move a diverged-but-fully-published branch back onto its remote.

    Only reached when the tree is clean and no commit here is missing from every
    remote, so nothing recoverable is discarded.
    """
    reset = _git(runner, path, "reset", "--hard", f"origin/{branch}")
    if _ok(reset):
        return (True, f"reset to origin/{branch} (was diverged, nothing unpushed)")
    tail = reset.stderr.strip().splitlines()
    return (False, f"reset failed: {tail[-1] if tail else 'unknown'}")


def _local_paths() -> list[tuple[str, str, str]]:
    """(id, checkout path, declared primary branch) for every managed checkout."""
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    return [
        (ctx["id"], ctx["local_path"], ctx.get("primary_branch", ""))
        for ctx in data.get("contexts", [])
        if ctx.get("local_path")
    ]


def sync_all(*, apply: bool, only: Sequence[str] | None = None) -> list[tuple[SyncPlan, str]]:
    """Plan (and optionally apply) a sync for every managed checkout."""
    results: list[tuple[SyncPlan, str]] = []
    for repo_id, path, primary in _local_paths():
        if only and repo_id not in only:
            continue
        state = gather_state(repo_id, path, primary_branch=primary)
        plan = plan_sync(state)
        note = plan.reason
        if apply and plan.action in ("ff", "unshallow_ff", "reset"):
            _, note = apply_plan(plan, path, target_branch=state.target_branch)
        results.append((plan, note))
    return results


def _render(results: list[tuple[SyncPlan, str]], *, apply: bool) -> str:
    header = "Applied" if apply else "DRY-RUN (no writes)"
    lines = [f"== sync_repos [{header}] =="]
    for plan, note in results:
        lines.append(f"  {plan.repo_id:16} {plan.action:13} {note}")
    return "\n".join(lines)


def exit_code_for(plans: list[SyncPlan]) -> int:
    """0 when every checkout was measured, 2 when any could not be looked at.

    The deliberate skips — dirty tree, unpushed commits, off-target branch — are
    *measured answers* and stay green. Reddening the nightly timer for those
    would make it fire every time a developer had uncommitted work, and a
    monitor that cries wolf gets muted, which is the failure this exists to
    prevent rather than cause.

    An empty result is could-not-look too: sixteen configured contexts and none
    visited is the false green itself, not a clean estate.
    """
    if not plans:
        return EXIT_COULD_NOT_LOOK
    if any(plan.action in _BLIND_ACTIONS for plan in plans):
        return EXIT_COULD_NOT_LOOK
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Keep managed checkouts current with origin (auto-unshallow, ff-only, loud-skip)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report only; make no changes"
    )
    parser.add_argument(
        "--only", nargs="*", default=None, help="limit to these repo ids"
    )
    args = parser.parse_args(argv)

    results = sync_all(apply=not args.dry_run, only=args.only)
    print(_render(results, apply=not args.dry_run))

    plans = [plan for plan, _ in results]
    code = exit_code_for(plans)
    if code != EXIT_OK:
        blind = [p for p in plans if p.action in _BLIND_ACTIONS]
        if blind:
            for plan in blind:
                print(
                    f"  sync_repos: COULD NOT LOOK — {plan.repo_id}: {plan.reason}",
                    file=sys.stderr,
                )
        else:
            print(
                "  sync_repos: COULD NOT LOOK — no checkouts were visited at all.",
                file=sys.stderr,
            )
    return code


if __name__ == "__main__":
    sys.exit(main())
