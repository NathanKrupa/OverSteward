#!/usr/bin/env python3
# ABOUTME: Pre-commit gate — formats the staged Python files and blocks the commit if any changed.
# ABOUTME: Canonical (OverSteward shared/scripts/dev/); deployed byte-identical to each repo's scripts/dev/.
"""Pre-commit backstop that keeps every commit already-formatted (OS#78).

A verify run that applies formatting *after* a commit leaves the rewrite
unstaged, so the push ships unformatted bytes and CI's ``ruff format --check``
fails on a locally-green tree. ``require_formatted_commit.py`` catches that at
verify time; this hook prevents it upstream — if a commit can never contain
unformatted Python, there is no residue for verify to find.

It formats only the Python files that are staged, then blocks the commit when
any of them changed, naming them so the developer re-stages. Blocking rather
than staging the rewrite itself is deliberate: a hook that silently amends what
is about to be committed changes bytes the developer never saw.

Formatting is delegated to the repo's own formatter with the repo's own config:
``ruff format`` discovers the nearest ``pyproject.toml``, so line length and
target version are the repo's, never this script's. ``--force-exclude`` makes
``extend-exclude`` apply to explicitly-named files too — without it, a hook that
passes paths would reformat the very canonical family each repo excludes to keep
byte-identical (OS#241).

Register it per repo as a ``local`` pre-commit hook, beside the other canonical
gates::

    - id: format-staged
      name: ruff format (staged Python)
      entry: uv run python scripts/dev/format_staged.py
      language: system
      pass_filenames: false
      always_run: true

Exit codes: ``0`` nothing to do or already formatted, ``1`` files were
reformatted (re-stage and commit again), ``2`` no formatter available or the
formatter itself failed.
"""

from __future__ import annotations

import argparse
import hashlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FORMATTER = ("ruff", "format", "--force-exclude")
VENV_BINDIRS = ("bin", "Scripts")

OK = 0
REFORMATTED = 1
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


def staged_python_files(root: Path) -> list[str]:
    """Staged paths that still exist on disk and end in ``.py``."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--",
            "*.py",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line and (root / line).is_file()]


def digests(root: Path, paths: list[str]) -> dict[str, str]:
    """Content hash per path, so a rewrite is detected without a second git call."""
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


def run_formatter(command: list[str], paths: list[str], root: Path) -> int:
    """Apply the formatter in place; its own output is passed through."""
    return subprocess.run([*command, *paths], cwd=str(root)).returncode


def resolve_command(spec: str | None, root: Path) -> list[str] | None:
    """The formatter to run: the caller's if given, else the repo's own."""
    return shlex.split(spec) if spec else find_formatter(root)


def _report_rewritten(paths: list[str]) -> None:
    print("[format-staged] the formatter rewrote staged files:", file=sys.stderr)
    for path in paths:
        print(f"    {path}", file=sys.stderr)
    print(
        "  Re-stage them and commit again:\n"
        f"      git add {' '.join(shlex.quote(path) for path in paths)}",
        file=sys.stderr,
    )


def format_staged(command: list[str], staged: list[str], root: Path) -> int:
    """Format the staged files, blocking the commit if any of them changed."""
    before = digests(root, staged)
    formatter_status = run_formatter(command, staged, root)
    if formatter_status != 0:
        print(
            f"[format-staged] formatter exited {formatter_status} — fix the reported\n"
            "  syntax errors before committing.",
            file=sys.stderr,
        )
        return UNUSABLE

    rewritten = sorted(path for path, sha in digests(root, staged).items() if sha != before[path])
    if not rewritten:
        return OK
    _report_rewritten(rewritten)
    return REFORMATTED


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    staged = staged_python_files(root)
    if not staged:
        return OK

    command = resolve_command(args.formatter, root)
    if not command:
        print(
            "[format-staged] no formatter found — install ruff in this repo's venv,\n"
            "  or pass --formatter '<command>'.",
            file=sys.stderr,
        )
        return UNUSABLE

    return format_staged(command, staged, root)


if __name__ == "__main__":
    raise SystemExit(main())
