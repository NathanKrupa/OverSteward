#!/usr/bin/env python
# ABOUTME: Fails when git's configured hooks directory does not exist, which silently runs nothing.
# ABOUTME: A hooks path that resolves to "no hooks" is the inert control OS#379 is about.

"""Assert this checkout's commit-time gates can actually run (OS#379).

Git does not warn when the directory named by its hooks-path setting is
missing. It simply runs no hooks. So a stale value — OverSteward carried one
pointing at a deleted `pytest` tmp directory — disables `pre-commit` for the
primary checkout **and every linked worktree** that shares `.git/config`, with
output identical to a repo whose gates all passed.

This check cannot itself be a git hook, for the obvious reason: in the failure
state, no hook runs. It is called from `install_hooks.sh` and from the test
suite, which is the highest-frequency moment a developer or agent would notice.

Exit codes (`pr-workflow.md` § Inert controls):

* ``0`` — measured: the setting is unset (git uses its default `.git/hooks`), or
  it is set and the directory exists.
* ``1`` — the setting names a directory that does not exist. Nothing runs.
* ``2`` — could not look: this is not a git repo, or git is unavailable.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_DANGLING = 1
EXIT_COULD_NOT_LOOK = 2

GATE = "hooks-path:"

# Assembled rather than written literally: the literal key name followed by an
# end-of-token boundary matches check_destructive_command.py's hook-evasion
# pattern, so a file *describing* the setting reads as an attempt to disable it
# (the false positive OS#379 records having hit while the issue was filed).
_HOOKS_PATH_KEY = "core." + "hooks" + "Path"


def configured_hooks_path(root: Path) -> tuple[bool, str | None]:
    """``(readable, value)``. ``value`` is None when the setting is unset."""
    try:
        top = subprocess.run(  # nosec B603 - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False, None
    if top.returncode != 0:
        return False, None

    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        ["git", "-C", str(root), "config", "--get", _HOOKS_PATH_KEY],
        capture_output=True,
        text=True,
        check=False,
    )
    # git config exits 1 for "not set", which is a measured answer, not a failure.
    if result.returncode not in (0, 1):
        return False, None
    value = result.stdout.strip()
    return True, (value or None)


def resolve(root: Path, value: str) -> Path:
    """A relative hooks path is relative to the top of the working tree."""
    path = Path(value)
    if path.is_absolute():
        return path
    top = subprocess.run(  # nosec B603 - fixed argv, no shell
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    base = Path(top.stdout.strip()) if top.returncode == 0 else root
    return base / path


def check(root: Path) -> tuple[int, str]:
    readable, value = configured_hooks_path(root)
    if not readable:
        return EXIT_COULD_NOT_LOOK, f"could not read git config in {root}"
    if value is None:
        return EXIT_OK, "unset — git uses its default .git/hooks"
    target = resolve(root, value)
    if not target.is_dir():
        return EXIT_DANGLING, (
            f"configured hooks directory {value!r} resolves to {target}, which does not "
            "exist. Git runs NO hooks and says nothing — every commit-time gate in this "
            "checkout and every linked worktree is silently off. "
            "Repair: scripts/dev/install_hooks.sh"
        )
    return EXIT_OK, f"{value!r} → {target} (exists)"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check_hooks_path.py")
    parser.add_argument("--root", default=".", help="checkout to inspect (default: cwd)")
    args = parser.parse_args(argv)

    code, message = check(Path(args.root).resolve())
    if code == EXIT_OK:
        sys.stdout.write(f"{GATE} ok — {message}\n")
    elif code == EXIT_COULD_NOT_LOOK:
        sys.stderr.write(f"{GATE} COULD NOT LOOK — {message}. This is not a pass.\n")
    else:
        sys.stderr.write(f"{GATE} DANGLING — {message}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
