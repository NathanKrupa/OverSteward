# ABOUTME: Dispatch watchdog service — has a dispatched agent's work moved within the warn window?
# ABOUTME: Reads the dispatch worktree (commits, .review* files, .verify-marker) and the remote branch.
"""Tell a dispatched agent that is looping from one that is still working.

A looping agent retries one failing step for hours and never reaches a terminal
state, so no completion notification fires (AG#947, 2026-06-21: ~2.5h and 397
turns on a live-DB seam read it could not satisfy). The watchdog rings when the
agent's work has not moved for ``warn_min`` minutes.

Work is read from the dispatch worktree, ``<checkout>/.claude/worktrees/dispatch-<n>``,
as well as the remote. A pushed branch alone cannot be the signal: in the repos
whose pre-push hook refuses a push until ``make verify`` has run at HEAD
(aigranthelper, grantspider, ai-assistants, exchequer) or runs the full gate on
every push (fiscus), the pre-round-1 sequence pushes only after review and the
full gate, one to three hours in, so a healthy run and a stalled one looked the
same until then (OS#632). The signals, any of which counts as movement:

* ``commit`` — the worktree's HEAD, whatever branch it is on, so a branch the
  issue pins outside the ``issue-<n>-`` pattern is still seen (OS#494, OS#498);
* ``review files`` — the name and mtime of every ``.review*`` file at the
  worktree root (the assembler's ``.review-rounds`` and input, the reviewer's
  captures);
* ``verify marker`` — the mtime of ``.verify-marker``, written when ``make verify`` passes;
* ``remote branch`` — the ``refs/heads/*issue-<n>*`` refs on the remote.

None of them depends on a heartbeat push (OS#569). A reading that could not be
taken (``None``) carries the previous reading forward, so a network blip on the
remote probe is never mistaken for movement. The run is finished once a
worktree that was seen is gone: the agent tears it down at the end of every run.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

#: Minutes with nothing moving before the alert. A quiet stretch is legitimate
#: while one review round or one ``make verify`` runs; 40- and 45-minute alerts
#: fired on healthy agents in exactly those stretches on 2026-11-11, which is why
#: the stepping-away skill already asked for 60 or more.
DEFAULT_WARN_MIN = 60
DEFAULT_POLL_SEC = 60
WORKTREE_DIR = Path(".claude") / "worktrees"
VERIFY_MARKER = ".verify-marker"
_GIT_TIMEOUT_S = 30

#: Exit codes: the run ended (its worktree was torn down), it stalled, or the
#: checkout to read could not be found.
EXIT_FINISHED = 0
EXIT_UNLOCATED = 2
EXIT_STALLED = 3

Marks = Mapping[str, str | None]


@dataclass(frozen=True)
class ProgressSnapshot:
    """One reading of every signal. ``""`` is absent; ``None`` could not be read."""

    worktree_present: bool
    marks: Marks


@dataclass(frozen=True)
class ProgressVerdict:
    """Outcome of one check: a status, whether to alert now, and why."""

    status: str  # "watching" | "progressing" | "stalled" | "finished"
    should_alert: bool
    reason: str

    @property
    def terminal(self) -> bool:
        return self.status in ("stalled", "finished")


def worktree_path(checkout: Path, issue: int) -> Path:
    """The dispatch worktree the playbook (step 5) creates for ``issue``."""
    return checkout / WORKTREE_DIR / f"dispatch-{issue}"


def checkout_for(full_name: str, contexts: Iterable[Mapping]) -> Path | None:
    """The ``local_path`` of the registry context whose ``repo`` URL is ``full_name``."""
    wanted = full_name.lower().removesuffix(".git")
    for ctx in contexts:
        repo = str(ctx.get("repo") or "").lower().removesuffix(".git")
        if repo.endswith("/" + wanted) and ctx.get("local_path"):
            return Path(ctx["local_path"])
    return None


def carry_forward(previous: Marks, current: Marks) -> dict[str, str | None]:
    """``current``, with each unreadable (``None``) reading replaced by the previous one."""
    keys = list(dict.fromkeys([*previous, *current]))
    return {k: previous.get(k) if current.get(k) is None else current[k] for k in keys}


def moved_signals(previous: Marks, current: Marks) -> list[str]:
    """Names of the signals whose reading changed. ``current`` is already carried forward.

    A signal never yet read (``None`` before) is taking its baseline, not moving.
    """
    keys = dict.fromkeys([*previous, *current])
    return [
        k for k in keys if previous.get(k) is not None and previous.get(k) != current.get(k)
    ]


def assess_dispatch_progress(
    *,
    idle_min: float,
    moved: list[str],
    worktree_seen: bool,
    worktree_present: bool,
    warn_min: float = DEFAULT_WARN_MIN,
) -> ProgressVerdict:
    """Decide dispatch health from what moved and how long nothing has.

    A worktree seen and now gone is a finished run. Any moved signal is
    progress. Nothing moved for ``warn_min`` is a probable silent loop.
    """
    if worktree_seen and not worktree_present:
        return ProgressVerdict("finished", False, "the dispatch worktree was torn down")
    if moved:
        return ProgressVerdict("progressing", False, "moved: " + ", ".join(moved))
    if idle_min >= warn_min:
        where = "" if worktree_seen else "; no dispatch worktree was ever seen"
        return ProgressVerdict(
            "stalled",
            True,
            f"nothing moved for ~{idle_min:.0f}m (warn baseline {warn_min:.0f}m: commits, "
            f".review* files, {VERIFY_MARKER}, remote branch){where} — probable silent loop",
        )
    return ProgressVerdict(
        "watching", False, f"quiet for ~{idle_min:.0f}m (warn at {warn_min:.0f}m)"
    )


def _mtime(path: Path) -> str:
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return ""


def _review_files(worktree: Path) -> str:
    return ";".join(f"{p.name}@{_mtime(p)}" for p in sorted(worktree.glob(".review*")))


def _head(worktree: Path, runner: Callable) -> str | None:
    try:
        result = runner(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def remote_branches(full_name: str, issue: int, *, runner: Callable = subprocess.run) -> str | None:
    """The remote's ``*issue-<n>*`` refs as text, ``""`` for none, ``None`` if the probe failed."""
    try:
        result = runner(
            ["git", "ls-remote", f"https://github.com/{full_name}.git", f"refs/heads/*issue-{issue}*"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 0) != 0:
        return None
    return getattr(result, "stdout", "").strip()


def read_snapshot(
    worktree: Path,
    remote_probe: Callable[[], str | None],
    *,
    runner: Callable = subprocess.run,
) -> ProgressSnapshot:
    """Read every signal once."""
    present = worktree.is_dir()
    return ProgressSnapshot(
        worktree_present=present,
        marks={
            "commit": _head(worktree, runner) if present else "",
            "review files": _review_files(worktree) if present else "",
            "verify marker": _mtime(worktree / VERIFY_MARKER) if present else "",
            "remote branch": remote_probe(),
        },
    )


def watch(
    read: Callable[[], ProgressSnapshot],
    *,
    warn_min: float = DEFAULT_WARN_MIN,
    poll_sec: float = DEFAULT_POLL_SEC,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
    report: Callable[[ProgressVerdict, float], None] = lambda verdict, elapsed_min: None,
) -> ProgressVerdict:
    """Poll until the run finishes or nothing has moved for ``warn_min``.

    The first reading is the baseline; the idle clock starts at arming, so a
    worktree that never appears or never moves stalls after ``warn_min``.
    ``report`` receives every ``progressing`` verdict with the minutes elapsed.
    """
    start = last_move = clock()
    first = read()
    marks = carry_forward({}, first.marks)
    seen = first.worktree_present
    while True:
        sleeper(poll_sec)
        snapshot = read()
        now = clock()
        current = carry_forward(marks, snapshot.marks)
        moved = moved_signals(marks, current)
        marks = current
        if moved:
            last_move = now
        verdict = assess_dispatch_progress(
            idle_min=(now - last_move) / 60.0,
            moved=moved,
            worktree_seen=seen,
            worktree_present=snapshot.worktree_present,
            warn_min=warn_min,
        )
        seen = seen or snapshot.worktree_present
        if verdict.status == "progressing":
            report(verdict, (now - start) / 60.0)
        if verdict.terminal:
            return verdict


def exit_code(verdict: ProgressVerdict) -> int:
    """``EXIT_STALLED`` for an alert, ``EXIT_FINISHED`` for a run that ended."""
    return EXIT_STALLED if verdict.should_alert else EXIT_FINISHED
