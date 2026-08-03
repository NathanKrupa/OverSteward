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

import shutil
import subprocess
import sys
from pathlib import Path


def _gaudi_binary() -> str:
    """Resolve gaudi to an absolute path so subprocess invocation does not
    depend on PATH lookup (bandit B607)."""
    found = shutil.which("gaudi") or shutil.which("gaudi.exe")
    if not found:
        sys.stderr.write("gaudi binary not found on PATH; install gaudi-linter\n")
        sys.exit(2)
    return found


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
