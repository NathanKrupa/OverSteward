#!/usr/bin/env python3
# ABOUTME: Dispatch watchdog — alert the operator when a dispatched agent runs long with no branch pushed.
# ABOUTME: Silent-loop guard; stdlib-only, pure assessment split from git IO so the logic is unit-tested.
"""Catch a dispatched agent that is looping instead of producing a PR.

A `<repo>-dev` dispatch is expected to push its issue branch within minutes. When
the environment can't satisfy a step it should run (e.g. the test DB / docker
container is down so `make verify` can never pass), a misbehaving agent may
*loop* — retrying the same failing step for hours, burning Max quota, never
reaching a terminal state and so never firing a completion notification. The
operator can't tell that apart from "still working" without looking.

This watchdog watches the one signal that distinguishes the two: a pushed branch.
A healthy dispatch publishes `…/issue-<n>-…` early; a looping one never does. If
no branch appears within ``warn_min`` minutes, the watchdog rings the bell so the
operator can inspect the agent transcript and ``TaskStop`` it if it is churning.

Run it once per dispatch, armed right after the agent is launched (the operator
backgrounds it). Pure assessment is split from the git IO so the decision logic
is unit-tested without a network or a clock. Stdlib-only by design.

First lesson behind it: AG#947, 2026-06-21 — an agent looped ~2.5h / 397 turns on
a live-DB seam read it could not satisfy in the sandbox before anyone noticed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_WARN_MIN = 22
DEFAULT_POLL_SEC = 60
_LS_REMOTE_TIMEOUT_S = 30


@dataclass(frozen=True)
class ProgressVerdict:
    """Outcome of one progress check: a status, whether to alert now, and why."""

    status: str  # "progressing" | "watching" | "stalled"
    should_alert: bool
    reason: str


def assess_dispatch_progress(
    elapsed_min: float, branch_present: bool, warn_min: float = DEFAULT_WARN_MIN
) -> ProgressVerdict:
    """Decide dispatch health from elapsed time and whether a branch was pushed.

    A pushed branch means the agent is producing work — healthy, stop watching.
    No branch once ``elapsed_min`` reaches ``warn_min`` means the agent has run
    long with nothing to show — a probable silent loop; alert. In between, keep
    watching quietly.
    """
    if branch_present:
        return ProgressVerdict(
            status="progressing",
            should_alert=False,
            reason=f"branch pushed after ~{elapsed_min:.0f}m — agent is producing work",
        )
    if elapsed_min >= warn_min:
        return ProgressVerdict(
            status="stalled",
            should_alert=True,
            reason=(
                f"no branch pushed after ~{elapsed_min:.0f}m (>= warn {warn_min:.0f}m) — "
                "probable silent loop"
            ),
        )
    return ProgressVerdict(
        status="watching",
        should_alert=False,
        reason=f"no branch yet at ~{elapsed_min:.0f}m (warn at {warn_min:.0f}m) — watching",
    )


def branch_exists(
    full_name: str, issue: int, *, runner: Callable = subprocess.run
) -> bool:
    """True if a remote branch matching ``issue-<n>`` exists on ``full_name``.

    ``runner`` is injected for testing; it defaults to ``subprocess.run``. A
    failed probe (network blip, auth) is treated as "no branch yet" — the next
    poll retries, and a persistent failure surfaces as a stall alert rather than
    a crash.
    """
    remote = f"https://github.com/{full_name}.git"
    try:
        result = runner(
            ["git", "ls-remote", remote, f"refs/heads/*issue-{issue}*"],
            capture_output=True,
            text=True,
            timeout=_LS_REMOTE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(getattr(result, "stdout", "").strip())


def watch(
    full_name: str,
    issue: int,
    *,
    warn_min: float = DEFAULT_WARN_MIN,
    poll_sec: float = DEFAULT_POLL_SEC,
    branch_check: Callable[[str, int], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ProgressVerdict:
    """Poll until the branch appears (progressing) or ``warn_min`` elapses (stalled).

    Returns the terminal verdict. ``branch_check``/``sleeper``/``clock`` are
    injected for testing; they default to the real git probe, ``time.sleep`` and
    ``time.monotonic``.
    """
    check = branch_check or (lambda fn, n: branch_exists(fn, n))
    start = clock()
    while True:
        elapsed_min = (clock() - start) / 60.0
        verdict = assess_dispatch_progress(elapsed_min, check(full_name, issue), warn_min)
        if verdict.status != "watching":
            return verdict
        sleeper(poll_sec)


def _alert_text(full_name: str, issue: int, reason: str) -> str:
    return (
        f"⏱ Dispatch watchdog: {full_name}#{issue} — {reason}. "
        "Check the agent transcript's turn count; TaskStop and re-dispatch if it is looping."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch watchdog — alert when an agent runs long with no branch pushed."
    )
    parser.add_argument("full_name", help="owner/repo, e.g. NathanKrupa/aigranthelper")
    parser.add_argument("issue", type=int, help="issue number being dispatched")
    parser.add_argument(
        "--warn-min", type=float, default=DEFAULT_WARN_MIN, help="minutes before a stall alert"
    )
    parser.add_argument(
        "--poll-sec", type=float, default=DEFAULT_POLL_SEC, help="seconds between branch probes"
    )
    args = parser.parse_args(argv)

    verdict = watch(
        args.full_name, args.issue, warn_min=args.warn_min, poll_sec=args.poll_sec
    )
    if verdict.should_alert:
        print(_alert_text(args.full_name, args.issue, verdict.reason))
        return 3
    print(f"{verdict.status}: {verdict.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
