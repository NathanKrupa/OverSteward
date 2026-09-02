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
  * Filters input to ``*.py`` files (pre-commit ``types: [python]``
    already does this; the filter is defence-in-depth).
  * Runs ``gaudi check --severity error --exit-code FILE`` for each.
  * Prints any error output verbatim. Exits 1 if any file produced an
    error finding, else 0.
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


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv if a.endswith(".py") and Path(a).is_file()]
    if not files:
        return 0

    gaudi = _gaudi_binary()
    any_failed = False
    for f in files:
        # Args are a resolved binary path + literal flags + filtered *.py
        # paths from pre-commit. No shell, no untrusted input — B603 is the
        # generic "subprocess used" warning, not a real signal here.
        result = subprocess.run(  # nosec B603
            [gaudi, "check", "--severity", "error", "--exit-code", str(f)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            any_failed = True
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
