#!/usr/bin/env python3
# ABOUTME: Applies the repo's formatter, then requires every tracked file to match HEAD.
# ABOUTME: Canonical (OverSteward shared/scripts/dev/); deployed byte-identical to each repo's scripts/dev/.
"""Format-then-assert-clean gate for a local verify run (OS#78).

A verify script that *checks* formatting burns a whole cycle every time a
freshly-written file is unformatted, so the fix is to **apply** ``ruff format``
as verify's first step. Applying it alone, however, opens a worse hole:

1. commit
2. verify applies formatting — files change **after** the commit
3. verify writes its "HEAD is verified" marker
4. the formatter's rewrite sits in the working tree, unstaged
5. push ships the *committed* (unformatted) bytes
6. CI's ``ruff format --check`` fails on a locally-green tree

The marker certifies a commit whose bytes nobody verified. This gate closes
that hole: run the formatter, then require the tracked tree to be identical to
HEAD. If anything differs, the verified state is not the committed state, so it
fails loudly *before* the marker is written and names the fix.

The two ways the tree can differ are reported separately, because the fixes
differ: files this run reformatted (formatter residue — amend it into the
commit) and files that were already modified before this run (work in progress
— commit or stash it).

Formatting is delegated to the repo's own formatter with the repo's own config:
``ruff format`` discovers the nearest ``pyproject.toml``, so line length, target
version, and ``extend-exclude`` (which is how each repo keeps its hands off this
canonical family — OS#241) are the repo's, never this script's.

Usage::

    python scripts/dev/require_formatted_commit.py
    python scripts/dev/require_formatted_commit.py apps config scripts
    python scripts/dev/require_formatted_commit.py --formatter "black ."

Exit codes: ``0`` tree matches HEAD, ``1`` residue or uncommitted work,
``2`` no formatter available or the formatter itself failed.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FORMATTER = ("ruff", "format")
VENV_BINDIRS = ("bin", "Scripts")

OK = 0
NOT_CLEAN = 1
UNUSABLE = 2


def repo_root(start: str) -> Path:
    """Top level of the git tree containing ``start``."""
    proc = subprocess.run(
        ["git", "-C", start, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return Path(start).resolve()
    return Path(proc.stdout.strip())


def find_formatter(root: Path) -> list[str] | None:
    """Default formatter command: the repo's own ruff, else one on PATH."""
    for bindir in VENV_BINDIRS:
        for name in ("ruff", "ruff.exe"):
            candidate = root / ".venv" / bindir / name
            if candidate.is_file():
                return [str(candidate), *DEFAULT_FORMATTER[1:]]
    found = shutil.which(DEFAULT_FORMATTER[0])
    return [found, *DEFAULT_FORMATTER[1:]] if found else None


def changed_against_head(root: Path) -> set[str]:
    """Tracked paths that differ from HEAD, staged or not."""
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "HEAD", "--"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return set()
    return {line for line in proc.stdout.splitlines() if line}


def run_formatter(command: list[str], targets: list[str], root: Path) -> int:
    """Apply the formatter in place; its own output is passed through."""
    return subprocess.run([*command, *targets], cwd=str(root)).returncode


def _report(residue: set[str], preexisting: set[str]) -> None:
    print(
        "[format-gate] the working tree does not match HEAD after formatting.",
        file=sys.stderr,
    )
    if residue:
        print("  reformatted by this run (formatter residue):", file=sys.stderr)
        for path in sorted(residue):
            print(f"    {path}", file=sys.stderr)
        print(
            "  Amend the formatter residue into the commit, then re-run:\n"
            "      git add -u && git commit --amend --no-edit",
            file=sys.stderr,
        )
    if preexisting:
        print("  modified before this run (uncommitted work):", file=sys.stderr)
        for path in sorted(preexisting):
            print(f"    {path}", file=sys.stderr)
        print("  Commit or stash it, then re-run.", file=sys.stderr)
    print(
        "  Verifying now would certify HEAD, not these bytes — the push would ship\n"
        "  the unformatted commit and CI's format check would fail on it.",
        file=sys.stderr,
    )


def resolve_command(spec: str | None, root: Path) -> list[str] | None:
    """The formatter to run: the caller's if given, else the repo's own."""
    return shlex.split(spec) if spec else find_formatter(root)


def require_formatted_commit(command: list[str], targets: list[str], root: Path) -> int:
    """Format, then require every tracked path to be identical to HEAD."""
    before = changed_against_head(root)
    formatter_status = run_formatter(command, targets, root)
    if formatter_status != 0:
        print(
            f"[format-gate] formatter exited {formatter_status} — fix the reported\n"
            "  syntax errors before verifying.",
            file=sys.stderr,
        )
        return UNUSABLE

    after = changed_against_head(root)
    if not after:
        print("[format-gate] ok: formatted, and the tree matches HEAD.")
        return OK

    _report(residue=after - before, preexisting=after & before)
    return NOT_CLEAN


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        default=None,
        help="Paths to format (default: the whole repo, minus its config's excludes).",
    )
    parser.add_argument("--root", default=".", help="Repo to gate (default: cwd).")
    parser.add_argument(
        "--formatter",
        default=None,
        help="Formatter command to apply (default: the repo's ruff format).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root(args.root)
    command = resolve_command(args.formatter, root)
    if not command:
        print(
            "[format-gate] no formatter found — install ruff in this repo's venv,\n"
            "  or pass --formatter '<command>'.",
            file=sys.stderr,
        )
        return UNUSABLE

    return require_formatted_commit(command, args.targets or ["."], root)


if __name__ == "__main__":
    raise SystemExit(main())
