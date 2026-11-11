# ABOUTME: Judges a captured adversarial-review result and recovers the scratch copy of a blind round.
# ABOUTME: A result with no verdict fence certified nothing; its leftover mutants are recorded, restored, torn down.

"""The check a dev card runs on the reviewer's captured result (OS#682).

The reviewer runs headless (``claude -p``) and the process ends when its turn
ends. A reviewer that backgrounded its own mutation loop returned "still
running in the background", exit 0, no ``reviewer-verdict`` fence, and left a
live mutant in its ``<worktree>.review`` scratch copy. That launch was billed
and certified nothing: a **blind round**.

This module tells the two apart and, for a blind round, does the recovery in a
fixed order, each step only after the one before it held:

1. **record** the result and the scratch copy's status and diff beside the
   capture, as ``.review-verdict-<N>.blind-<k>.md``;
2. **restore** every path the copy lists from ``HEAD`` by content, or delete it
   where ``HEAD`` has no such path, and require a clean status afterwards;
3. **tear the copy down** through ``worktree_doctor.py``, which drops its bench
   databases after removing it.

The relaunch is the caller's: the card relaunches once on the same input. The
record count is what makes a second blind round on the same review round
distinguishable from the first, so it stops instead of relaunching again. The
assembler is never re-run, so a blind round is not a review round.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed git and doctor argv, no shell
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from oversteward.review_verdict import MalformedVerdictError, has_verdict_block, parse_verdict

EXIT_VERDICT = 0
EXIT_BLIND = 1
EXIT_STOP = 2
EXIT_SECOND_BLIND = 3

#: The reviewer's scratch copy is the author's worktree path plus this suffix
#: (`shared/agents/adversarial-reviewer.md`).
SCRATCH_SUFFIX = ".review"

#: The capture names the dev cards write: a round's capture, and its one relaunch.
CAPTURE_NAME = re.compile(r"^\.review-verdict-(?P<round>\d+)(?:-relaunch)?\.md$")

#: Runs git with the given arguments; stdout and stderr are captured as bytes.
Git = Callable[[list[str]], "subprocess.CompletedProcess[bytes]"]
#: Tears down ``scratch`` for the ``primary`` checkout; returns the doctor's exit code.
Teardown = Callable[[Path, Path], int]

DOCTOR = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "worktree_doctor.py"


@dataclass(frozen=True)
class Outcome:
    """An exit code and the sentence that explains it."""

    code: int
    message: str


def run_git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Git, never through a shell; an absent git is a failed call, not a traceback."""
    try:
        return subprocess.run(["git", *args], capture_output=True, check=False)  # nosec B603 B607
    except OSError as exc:
        return subprocess.CompletedProcess(args, 127, b"", str(exc).encode())


def doctor_teardown(scratch: Path, primary: Path) -> int:
    """``worktree_doctor.py teardown`` — the only sanctioned removal of a worktree."""
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [sys.executable, str(DOCTOR), "teardown", str(scratch), "--repo", str(primary)],
        check=False,
    ).returncode


def check_capture(
    capture: Path, *, git: Git = run_git, teardown: Teardown = doctor_teardown
) -> Outcome:
    """Whether ``capture`` holds a verdict; for a blind round, the recovery's outcome."""
    named = CAPTURE_NAME.match(capture.name)
    if named is None:
        return Outcome(
            EXIT_STOP,
            f"{capture.name} is not a capture: expected .review-verdict-<N>.md "
            "or .review-verdict-<N>-relaunch.md in the author's worktree.",
        )
    try:
        text = capture.read_text(encoding="utf-8")
    except OSError as exc:
        return Outcome(EXIT_STOP, f"could not read {capture}: {exc}")
    if has_verdict_block(text):
        try:
            verdict = parse_verdict(text)
        except MalformedVerdictError as exc:
            return Outcome(EXIT_STOP, f"the reviewer-verdict fence cannot be read: {exc}")
        return Outcome(EXIT_VERDICT, f"{verdict.verdict}, {verdict.findings} finding(s).")
    return _blind_round(capture, named.group("round"), text, git=git, teardown=teardown)


def _blind_round(
    capture: Path, round_number: str, text: str, *, git: Git, teardown: Teardown
) -> Outcome:
    worktree = capture.parent
    count = len(list(worktree.glob(f".review-verdict-{round_number}.blind-*.md"))) + 1
    record = worktree / f".review-verdict-{round_number}.blind-{count}.md"
    scratch = worktree.with_name(worktree.name + SCRATCH_SUFFIX)
    state = _scratch_state(scratch, git) if scratch.exists() else None
    if scratch.exists() and state is None:
        return Outcome(EXIT_STOP, f"could not read the state of {scratch}; recover it by hand.")
    try:
        record.write_text(_record(round_number, count, text, scratch, state), encoding="utf-8")
    except OSError as exc:
        return Outcome(EXIT_STOP, f"could not write {record}: {exc}; nothing was restored.")
    if state is not None:
        refusal = _restore_and_tear_down(scratch, state[0], git=git, teardown=teardown)
        if refusal is not None:
            return Outcome(EXIT_STOP, f"{refusal} The blind round is recorded in {record}.")
    if count > 1:
        return Outcome(
            EXIT_SECOND_BLIND,
            f"blind round {count} on review round {round_number}: stop the pickup. "
            f"Recorded in {record}.",
        )
    return Outcome(
        EXIT_BLIND,
        f"no reviewer-verdict fence: recorded in {record}. Record the launch's usage, then "
        "relaunch once on the same input; the round count is unchanged.",
    )


def _scratch_state(scratch: Path, git: Git) -> tuple[list[str], str] | None:
    """The paths the copy differs from HEAD in, and its readable status plus diff."""
    status = git(["-C", str(scratch), "status", "--porcelain", "-z", "--untracked-files=all"])
    diff = git(["-C", str(scratch), "diff", "HEAD"])
    if status.returncode != 0 or diff.returncode != 0:
        return None
    paths = _status_paths(status.stdout)
    listing = "\n".join(paths) or "(clean)"
    return paths, f"## Status\n\n{listing}\n\n## Diff against HEAD\n\n```diff\n" + (
        diff.stdout.decode("utf-8", "replace") + "```\n"
    )


def _status_paths(porcelain: bytes) -> list[str]:
    """Every path in ``git status --porcelain -z`` output, a rename's source included."""
    paths: list[str] = []
    fields = porcelain.decode("utf-8", "surrogateescape").split("\0")
    index = 0
    while index < len(fields) and fields[index]:
        entry = fields[index]
        paths.append(entry[3:])
        if entry[0] in "RC":
            index += 1
            paths.append(fields[index])
        index += 1
    return paths


def _record(
    round_number: str, count: int, text: str, scratch: Path, state: tuple[list[str], str] | None
) -> str:
    copy = state[1] if state is not None else f"There was no scratch copy at {scratch}.\n"
    if state is not None and not state[0]:
        copy = f"The scratch copy at {scratch} was clean.\n"
    return (
        f"# Blind round {count} on review round {round_number}\n\n"
        f"## Result\n\n{text.strip() or '(empty)'}\n\n"
        f"## Scratch copy\n\n{scratch}\n\n{copy}"
    )


def _restore_and_tear_down(
    scratch: Path, paths: list[str], *, git: Git, teardown: Teardown
) -> str | None:
    """Each path back to its HEAD bytes, then the doctor; the reason it stopped, or None."""
    for path in paths:
        head = git(["-C", str(scratch), "show", f"HEAD:{path}"])
        target = scratch / path
        if head.returncode == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(head.stdout)
        elif target.is_file() or target.is_symlink():
            target.unlink()
    after = git(["-C", str(scratch), "status", "--porcelain", "--untracked-files=all"])
    left = after.stdout.decode("utf-8", "replace").strip()
    if after.returncode != 0 or left:
        return f"{scratch} is still not clean after the restore ({left or 'status failed'})."
    primary = _primary_checkout(scratch, git)
    if primary is None:
        return f"could not name the primary checkout of {scratch}."
    code = teardown(scratch, primary)
    if code != 0:
        return f"worktree_doctor.py teardown {scratch} refused (exit {code})."
    return None


def _primary_checkout(scratch: Path, git: Git) -> Path | None:
    """The first ``worktree`` line of ``git worktree list --porcelain``."""
    listing = git(["-C", str(scratch), "worktree", "list", "--porcelain"])
    if listing.returncode != 0:
        return None
    for line in listing.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree "))
    return None
