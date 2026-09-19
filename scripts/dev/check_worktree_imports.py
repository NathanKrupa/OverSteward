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

Exit codes are three-valued, because "the package is where it should be" and
"there is no package to look at" are different answers:

* ``0`` — the package resolves inside this tree. A measured pass.
* ``1`` — mismatch: it resolves somewhere else, and every gate that imports it
  is validating the wrong source.
* ``2`` — could not look: the package is not importable, so nothing was
  verified. This used to be ``0`` (OS#384).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_COULD_NOT_LOOK = 2


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
        # Not importable at all. This used to return 0 — identical to `ok:` —
        # on the reasoning that absence is "a different problem". It is a
        # *worse* one: this guard exists to prove the worktree's own `src/` is
        # what resolves, and a package that cannot be imported is a stronger
        # signal of a broken environment than the mismatch it looks for. Exit 2
        # ("could not look"), which is neither the clean code nor the mismatch
        # code, so a gate can tell the three apart (OS#384).
        print(
            f"[worktree-imports] COULD NOT LOOK: {args.package!r} is not importable, "
            f"so nothing was verified about {root}.\n"
            f"  Install the package, or export PYTHONPATH to this tree's source.",
            file=sys.stderr,
        )
        return EXIT_COULD_NOT_LOOK

    if root in found.parents or found == root:
        print(f"[worktree-imports] ok: {args.package} → {found}")
        return 0

    print(
        f"[worktree-imports] MISMATCH: {args.package} resolves to\n"
        f"    {found}\n"
        f"  but this tree is\n"
        f"    {root}\n"
        f"  Every gate that imports {args.package} is validating the WRONG source.\n"
        f'  Fix: export PYTHONPATH="{root / "src" if (root / "src").is_dir() else root}"',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
