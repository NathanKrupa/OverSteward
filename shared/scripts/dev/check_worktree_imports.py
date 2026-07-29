#!/usr/bin/env python3
# ABOUTME: Fails when a project package imports from outside the current tree (worktree venv trap).
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; byte-copied into each repo's scripts/dev/.

"""Guard against a gate validating the wrong source tree.

Session worktrees share the primary checkout's ``.venv`` (deps live there, and
duplicating them per worktree is wasteful). The editable install inside that
venv points its ``.pth`` at the **primary checkout's** source, so unless
``PYTHONPATH`` overrides it, importing the project package inside a worktree
resolves to the primary tree — not the code you are editing.

That is a silent wrong-answer in exactly the tools whose job is to tell you
whether a change is safe. It can produce a false failure (your edits are
invisible to the gate) or, worse, a false pass (a breaking change the gate never
saw). On GrantSpider #1854 it cost three full gate runs before anyone noticed
the gate was reading a different file than the one under edit.

``new-session.sh`` already writes a ``.envrc`` and prints the export, but both
are advisory — nothing fails when they are skipped. This script is the
non-advisory half: run it from a gate, and a mismatch stops the build instead of
quietly producing a meaningless green.

Usage::

    python scripts/dev/check_worktree_imports.py grantspider
    python scripts/dev/check_worktree_imports.py apps.research --root .

Exits 0 when the package resolves inside the tree (or is not installed at all —
absence is a different problem, not this one). Exits 1 on a mismatch, naming
both paths and the fix.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _resolve_package_path(name: str) -> Path | None:
    """Filesystem location the import system would use for ``name``.

    Import machinery only — the module is never executed, so this stays safe to
    run against a package with side-effectful imports.
    """
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).resolve()
    if spec.origin:
        return Path(spec.origin).resolve()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="Importable project package, e.g. 'grantspider'.")
    parser.add_argument(
        "--root",
        default=".",
        help="Tree the package must resolve inside (default: cwd).",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    found = _resolve_package_path(args.package)

    if found is None:
        # Not installed / not importable. That is a real problem, but a
        # different one — failing here would turn this guard into a second
        # source of confusing red.
        print(f"[worktree-imports] {args.package!r} is not importable — skipping check.")
        return 0

    if root in found.parents or found == root:
        print(f"[worktree-imports] ok: {args.package} → {found}")
        return 0

    print(
        f"[worktree-imports] MISMATCH: {args.package} resolves to\n"
        f"    {found}\n"
        f"  but this tree is\n"
        f"    {root}\n"
        f"  Every gate that imports {args.package} is validating the WRONG source.\n"
        f"  Fix: export PYTHONPATH=\"{root / 'src' if (root / 'src').is_dir() else root}\"",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
