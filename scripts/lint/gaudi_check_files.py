#!/usr/bin/env python
# ABOUTME: Pre-commit hook wrapper that runs `gaudi check --severity error`
# ABOUTME: per-file across the changed Python files passed by pre-commit.

"""Pre-commit wrapper for ``gaudi check --severity error``.

Why this wrapper:
  * ``gaudi check`` accepts only one positional path; pre-commit's
    ``pass_filenames: true`` passes N changed files at once.
  * Running ``gaudi check`` on the whole repo is multi-second; per-file is
    sub-second, so checking only the changed files keeps the commit-time
    cost in the sub-5-second budget for any reasonable PR.

Behaviour:
  * Runs ``gaudi check --severity error --exit-code FILE`` for each
    argument that is an existing ``*.py`` file.
  * Refuses any argument that is not one, naming it, rather than
    dropping it.
  * Prints any error output verbatim.

Exit codes, which are gaudi 0.3.0's own and must not be collapsed:

  * ``0`` — nothing was asked for, or every file asked for was parsed and
    none carried an error finding.
  * ``1`` — at least one file carried an error finding.
  * ``2`` — something could not be looked at: an argument that is not an
    existing ``*.py`` file, gaudi reporting an incomplete run (a file its
    parser skipped, a pack that failed to load), a crashed gaudi, or no
    gaudi beside this interpreter.

``2`` outranks ``1``: a file nobody could read must not be reported as a
finding, because fixing the findings would then turn the gate green while
that file was still never parsed. Neither may read as a pass.

An empty argument list is the one silence that is honest — pre-commit
invokes the hook with the staged Python files, so no arguments means none
were staged. "Nothing was requested" and "I was handed a path and could
not read it" are different answers and no longer share an exit code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Resolve the package from THIS checkout's `src/` — a session worktree's `.venv`
# is a symlink to the primary checkout's, whose `__editable__*.pth` names the
# primary `src/`. Same reasoning, and the same waiver, as trajectory_tags.py.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.gaudi_binary import gaudi_binary  # noqa: E402


def _gaudi_binary() -> str:
    """The gaudi installed beside this interpreter, or a loud exit 2.

    Was ``shutil.which``, which finds ``~/.local/bin/gaudi`` — a *different*
    installation on a different interpreter. In aigranthelper that one runs
    Python 3.11 and cannot parse PEP 758 ``except A, B:``; it skipped roughly
    three dozen files and exited 0, output indistinguishable from a clean run.
    Those files had a false-green local error gate for months (OS#424).

    Exit 2 rather than 0 when there is none: "gaudi is not installed" and
    "gaudi found no errors" must not exit the same.
    """
    found = gaudi_binary()
    if found is None:
        sys.stderr.write(
            "gaudi-check: COULD NOT LOOK — no gaudi beside this interpreter "
            f"({sys.executable}). Nothing was checked.\n"
            "  Install it into this environment: uv sync --extra dev\n"
            "  (A gaudi elsewhere on PATH is deliberately NOT used: a different "
            "interpreter's parser silently skips files it cannot read.)\n"
        )
        sys.exit(2)
    return str(found)


def _partition(argv: list[str]) -> tuple[list[Path], list[str]]:
    """The arguments that can be checked, and the ones that cannot.

    ``types: [python]`` already narrows pre-commit's list, so an argument
    reaching the second bucket means the caller and this gate disagree about
    what was going to be checked — which is worth a refusal, not a filter.
    """
    checkable: list[Path] = []
    unexaminable: list[str] = []
    for arg in argv:
        path = Path(arg)
        if arg.endswith(".py") and path.is_file():
            checkable.append(path)
        else:
            unexaminable.append(arg)
    return checkable, unexaminable


def main(argv: list[str]) -> int:
    checkable, unexaminable = _partition(argv)
    worst = 0
    if unexaminable:
        sys.stderr.write(
            "gaudi-check: COULD NOT LOOK — not an existing Python file:\n"
            + "".join(f"  {arg}\n" for arg in unexaminable)
            + "  Nothing was checked for these. They are not clean; they are unread.\n"
        )
        worst = 2
    if not checkable:
        return worst

    gaudi = _gaudi_binary()
    for f in checkable:
        # Args are a resolved binary path + literal flags + filtered *.py
        # paths from pre-commit. No shell, no untrusted input — B603 is the
        # generic "subprocess used" warning, not a real signal here.
        result = subprocess.run(  # nosec B603
            [gaudi, "check", "--severity", "error", "--exit-code", str(f)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            continue
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        # Only gaudi's 1 means "looked, and found something". Its 2 means the
        # run was incomplete, and anything else (a crash, a signal, a missing
        # subcommand) means the same thing less politely. `max` is what makes
        # the gate fail closed across files, whatever order they arrive in.
        worst = max(worst, 1 if result.returncode == 1 else 2)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
