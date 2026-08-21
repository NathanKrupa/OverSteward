#!/usr/bin/env python
# ABOUTME: Pre-commit gate asserting every lesson bullet in a changed trajectory note is tagged.
# ABOUTME: Thin shell over oversteward.trajectory_tags — parse argv, print, pick an exit code.

"""Pre-commit gate for trajectory-note `[category]` / `→ promote:` tags (OS#329).

Scope is whatever pre-commit hands it, which is exactly the notes the commit
adds or modifies. That is the whole forward-looking design: the 123 legacy
notes are never passed in, so nothing has to retro-tag them.

Exit codes are three-valued on purpose (pr-workflow.md § Inert controls):

* ``0`` — every note checked, no violations. Always prints the count it
  checked, because "all 4 notes clean" is a measurement and "ok" is a claim.
* ``1`` — violations found. Each names the file, the line, the bullet, and the
  allowed vocabulary.
* ``2`` — could not look: a path that does not exist, or a note carrying none
  of the three capture sections. Reporting that as ``0`` is the false green the
  gate exists to remove.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve the package from THIS checkout's `src/`, ahead of whatever the shared
# venv's editable install points at. STRUCT-010's usual remedy — "use the
# editable install" — is precisely what fails here: a session worktree's `.venv`
# is a symlink to the primary checkout's, whose `__editable__*.pth` names the
# *primary* `src/`. A commit-time gate that imported normally would therefore
# validate using the primary checkout's copy of this service, and would raise
# ImportError outright in any worktree branched before the service existed —
# including the one that introduced it. A gate must run the code of the tree it
# is gating, and pre-commit gives it no PYTHONPATH to say so with.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.trajectory_tags import (  # noqa: E402
    NoteReport,
    UnreadableNoteError,
    format_violation,
    validate_note,
)

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_COULD_NOT_LOOK = 2

#: Every line this gate prints is prefixed, so a pre-commit log names its author.
GATE = "trajectory-tags:"


def _collect(paths: list[Path]) -> tuple[list[NoteReport], list[str]]:
    """Validate each path, splitting results from the ones that could not be read."""
    reports: list[NoteReport] = []
    unreadable: list[str] = []
    for path in paths:
        try:
            reports.append(validate_note(path))
        except UnreadableNoteError as exc:
            unreadable.append(str(exc))
    return reports, unreadable


def _report(reports: list[NoteReport], unreadable: list[str]) -> int:
    """Print the verdict and return the exit code it earns."""
    violations = [v for report in reports for v in report.violations]
    for message in unreadable:
        sys.stderr.write(f"{GATE} COULD NOT LOOK — {message}\n")
    for violation in violations:
        sys.stderr.write(f"{format_violation(violation)}\n")

    if unreadable:
        sys.stderr.write(
            f"{GATE} {len(unreadable)} note(s) could not be validated. "
            "This is not a pass — fix the note's sections or the path.\n"
        )
        return EXIT_COULD_NOT_LOOK
    if violations:
        sys.stderr.write(
            f"{GATE} {len(violations)} untagged bullet(s) across "
            f"{len({v.path for v in violations})} note(s). Tag them at capture "
            "time — see documentation/trajectories/TEMPLATE.md.\n"
        )
        return EXIT_VIOLATIONS

    bullets = sum(report.bullets_checked for report in reports)
    sys.stdout.write(
        f"{GATE} {len(reports)} note(s), {bullets} lesson bullet(s) — all tagged.\n"
    )
    return EXIT_OK


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv if arg.endswith(".md")]
    if not paths:
        return EXIT_OK
    return _report(*_collect(paths))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
