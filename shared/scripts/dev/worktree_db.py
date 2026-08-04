#!/usr/bin/env python3
# ABOUTME: Names the Postgres database a checkout owns on the shared test container.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/scripts/dev/.
"""Give every checkout its own database on the one shared test container.

The local test bench used to be a single database at a fixed name, shared by
the primary checkout and every session worktree. Whoever migrated it last won,
silently, for everyone — so a dead agent's orphan alembic stamp could make every
gate in every tree vacuous, and two worktrees could never gate at the same time.

The fix is not a container per worktree: that is N postgres processes, N volumes
and runtime port discovery. Postgres already serves many databases from one
instance. So the container, its port and its credentials stay fixed, and only
the *database name* varies:

    primary checkout                        ->  grantspider_test
    .claude/worktrees/gs-2043-ci-lock       ->  grantspider_test_gs_2043_ci_lock

The primary checkout keeps the unsuffixed name, so anything that predates this
split — a committed URL in the docs, an operator's shell history — still points
where it always did.

    worktree_db.py                  # the name for the current tree
    worktree_db.py --tree <path>    # the name for another tree
    worktree_db.py --base other     # override the derived <project>_test stem

Every consumer must read the name from here rather than compute its own. Two
places deriving the same name independently is the split brain this exists to
prevent — one of them will be left behind.

Layer: INNER. Pure name derivation plus ``git rev-parse``; no database, no
docker, no business logic.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess  # list-form argv, no shell; git reads only
import sys
from pathlib import Path

#: PostgreSQL truncates identifiers at NAMEDATALEN-1 bytes. A name that
#: overflows is silently cut, and two worktrees whose names agree on the first
#: 63 characters would then share a database — the exact collision this module
#: exists to stop. Long names get hashed instead of cut.
MAX_IDENTIFIER = 63

#: Characters an unquoted PostgreSQL identifier can carry without ceremony.
_UNSAFE = re.compile(r"[^a-z0-9_]+")

#: Hex digits of path digest appended to a name that had to be shortened.
_DIGEST_LENGTH = 8

SUFFIX = "_test"


def sanitize(text: str) -> str:
    """Fold ``text`` into the lowercase identifier alphabet.

    Runs of anything outside ``[a-z0-9_]`` collapse to a single underscore, so
    ``GS-2043.ci lock`` and ``gs_2043_ci_lock`` reach the same shape. Leading
    and trailing underscores are dropped; a name that starts with a digit gets
    an underscore in front, because a bare leading digit is not a legal
    unquoted identifier.
    """
    folded = _UNSAFE.sub("_", text.lower()).strip("_")
    if not folded:
        return ""
    return f"_{folded}" if folded[0].isdigit() else folded


def _shorten(base: str, slug: str, key: str) -> str:
    """``base_slug`` cut to fit, with a digest of ``key`` keeping it unique.

    The digest is taken over the full worktree path rather than the truncated
    slug: two worktrees can share a 60-character prefix, but not a path.
    """
    digest = hashlib.blake2s(key.encode("utf-8"), digest_size=_DIGEST_LENGTH // 2).hexdigest()
    room = MAX_IDENTIFIER - len(base) - len("_") - len("_") - len(digest)
    if room <= 0:
        # The stem alone is near the limit; keep the digest and cut the stem,
        # since the digest is the only part carrying uniqueness.
        keep = MAX_IDENTIFIER - len("_") - len(digest)
        return f"{base[:keep]}_{digest}"
    return f"{base}_{slug[:room]}_{digest}"


def derive(base: str, worktree: str | None, *, key: str = "") -> str:
    """The database name for a tree.

    ``worktree`` is None for a primary checkout, which keeps ``base`` unchanged.
    ``key`` is the value hashed when the name has to be shortened — callers pass
    the worktree's absolute path.
    """
    slug = sanitize(worktree or "")
    if not slug:
        return base
    full = f"{base}_{slug}"
    if len(full) <= MAX_IDENTIFIER:
        return full
    return _shorten(base, slug, key or full)


def _git(tree: Path, *args: str) -> str | None:
    """One ``git -C tree`` read, or None when git has nothing to say."""
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", str(tree), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def primary_checkout(tree: Path) -> Path | None:
    """The checkout owning ``tree``'s git directory — a worktree's primary."""
    common = _git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).parent if common else None


def toplevel(tree: Path) -> Path | None:
    """The root of the working tree ``tree`` sits in."""
    top = _git(tree, "rev-parse", "--path-format=absolute", "--show-toplevel")
    return Path(top) if top else None


def is_linked_worktree(tree: Path) -> bool:
    """True when ``tree`` is a linked worktree rather than the primary checkout.

    A linked worktree's ``--git-dir`` lives under the primary's
    ``.git/worktrees/``, so the two paths differ; in the primary they agree.
    """
    own = _git(tree, "rev-parse", "--path-format=absolute", "--git-dir")
    common = _git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if own is None or common is None:
        return False
    return Path(own).resolve() != Path(common).resolve()


def base_name(primary: Path) -> str:
    """``<project>_test`` — the stem every tree of one repo shares."""
    return f"{sanitize(primary.name)}{SUFFIX}"


def database_name(tree: Path | None = None, *, base: str | None = None) -> str:
    """The database ``tree`` owns on the shared test container.

    Raises ``FileNotFoundError`` when ``tree`` is not inside a git checkout —
    the name is derived from the repository, so there is nothing to guess.
    """
    tree = Path(tree) if tree is not None else Path.cwd()
    primary = primary_checkout(tree)
    if primary is None:
        raise FileNotFoundError(f"not inside a git checkout: {tree}")
    stem = base if base is not None else base_name(primary)
    if not is_linked_worktree(tree):
        return stem
    root = toplevel(tree) or tree
    return derive(stem, root.name, key=str(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the test database name this checkout owns.",
    )
    parser.add_argument(
        "--tree",
        default=None,
        help="checkout to name a database for (default: the current directory)",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="override the derived <project>_test stem",
    )
    args = parser.parse_args(argv)
    try:
        print(database_name(args.tree, base=args.base))
    except FileNotFoundError as exc:
        print(f"worktree_db: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
