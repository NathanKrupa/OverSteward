# ABOUTME: INNER git reader for the abandoned-work sweep — each linked worktree's head, age, and landing.
# ABOUTME: The worktree list comes from worktree_doctor; this only asks git about each tree. Never removes one.

"""Which of a checkout's linked worktrees hold work that has not landed.

The list of worktrees is the doctor's (``worktree_doctor.worktree_checkouts``),
passed in by the caller, so there is one parser of ``git worktree list`` in the
estate. For each linked tree this asks git three things: its ``HEAD``, when that
commit was made, and whether it is already on ``origin/<trunk>`` in the primary
checkout. A tree whose directory is gone is reported as missing, not skipped.

Teardown is never this module's business: removal goes through
``worktree_doctor.py teardown``, which knows what a removal can orphan.
"""

from __future__ import annotations

import subprocess  # list-form argv, no shell
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: ``(path, branch or None)`` for every worktree, the primary checkout first.
Checkouts = Callable[[Path], list[tuple[Path, str | None]]]
GitRunner = Callable[[list[str]], subprocess.CompletedProcess]


class WorktreeReadError(RuntimeError):
    """git could not answer about a worktree — the sweep could not look."""


@dataclass(frozen=True, slots=True)
class Worktree:
    repo: str
    path: Path
    branch: str | None
    #: ``None`` when the directory no longer exists.
    last_commit_at: datetime | None
    landed: bool

    @property
    def missing(self) -> bool:
        return self.last_commit_at is None


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=60, check=False
    )


def _ask(git: GitRunner, args: list[str]) -> str:
    result = git(args)
    if result.returncode != 0:
        raise WorktreeReadError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _landed(git: GitRunner, primary: Path, head: str, trunk: str) -> bool:
    result = git(["-C", str(primary), "merge-base", "--is-ancestor", head, f"origin/{trunk}"])
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise WorktreeReadError(
        f"git could not tell whether {head} is on origin/{trunk} in {primary}: "
        f"{result.stderr.strip()}"
    )


def read_worktrees(
    repo: str, primary: Path, trunk: str, *, checkouts: Checkouts, git: GitRunner = run_git
) -> tuple[Worktree, ...]:
    """Every linked worktree of ``primary``, with whether its ``HEAD`` is on the trunk."""
    trees = checkouts(primary)[1:]
    found: list[Worktree] = []
    for path, branch in trees:
        if not path.is_dir():
            found.append(Worktree(repo, path, branch, last_commit_at=None, landed=False))
            continue
        head = _ask(git, ["-C", str(path), "rev-parse", "HEAD"])
        when = datetime.fromisoformat(_ask(git, ["-C", str(path), "log", "-1", "--format=%cI", head]))
        found.append(Worktree(repo, path, branch, when, _landed(git, primary, head, trunk)))
    return tuple(found)


__all__ = ["Checkouts", "GitRunner", "Worktree", "WorktreeReadError", "read_worktrees", "run_git"]
