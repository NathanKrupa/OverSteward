# ABOUTME: Which git tree the map is checked against per repo, and the reader that lists it.
# ABOUTME: The map's own repo reads its HEAD; every sibling fetches, then reads origin/<the branch it ships>.

"""Where an estate-map claim is looked up.

The map lives in OverSteward and is versioned with OverSteward's code, so its
OverSteward claims must hold at the map's own commit: that repo reads `HEAD`
of the checkout the map sits in. Every other repo is read on
`origin/<primary_branch or branch>` after a fetch of that same branch — the
resident checkouts run dozens to hundreds of commits stale, and a claim must
name what production runs (GS and AG ship `main` while defaulting to
`staging`).

Each failure this module recognises (no registry entry, no local_path, no
branch, an absent checkout, a failed fetch, a failed ls-tree) raises
CouldNotLook, which the checks turn into exit 2. Anything else is a crash, which
`scripts/estate_map.py` also exits 2 on. None of them may read as "nothing
missing".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

HEAD = "HEAD"


class CouldNotLook(Exception):
    """A tree could not be read. The message names the repo and the reason."""


class GitRunner(Protocol):
    def run(self, cwd: Path, *args: str) -> Any: ...


@dataclass(frozen=True)
class Checkout:
    repo: str
    #: None when the registry gives no local_path to read.
    root: Path | None
    ref: str
    #: The branch fetched before reading; None for the map's own repo.
    fetch_branch: str | None


def checkouts(registry: Mapping[str, Any], *, home_repo: str, home_root: Path) -> dict[str, Checkout]:
    found: dict[str, Checkout] = {}
    for ctx in registry.get("contexts") or []:
        repo = str(ctx.get("id"))
        if repo == home_repo:
            found[repo] = Checkout(repo, Path(home_root), HEAD, None)
            continue
        branch = str(ctx.get("primary_branch") or ctx.get("branch") or "")
        local = ctx.get("local_path")
        root = Path(local) if local else None
        found[repo] = Checkout(repo, root, f"origin/{branch}", branch)
    return found


class TreeReader:
    """Reads tracked paths from each repo's chosen ref, fetching each sibling once."""

    def __init__(self, git: GitRunner, found: Mapping[str, Checkout]) -> None:
        self._git = git
        self._found = found
        self._fetched: set[str] = set()

    def existing(self, repo: str, paths: Iterable[str]) -> set[str]:
        """The subset of `paths` (trailing `/` ignored) present on the repo's ref.

        A path is present when it, or a file under it, is tracked. Directories are read
        from the files beneath them because `git ls-tree` without `-r` descends into a
        directory that holds a deeper pathspec and then never prints the directory itself.
        """
        wanted = sorted({p.rstrip("/") for p in paths})
        present: set[str] = set()
        for tracked in self._ls_tree(repo, wanted, recursive=True):
            parts = tracked.split("/")
            present.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        return present.intersection(wanted)

    def files(self, repo: str, roots: Iterable[str]) -> list[str]:
        """Every tracked file under `roots` on the repo's ref."""
        return sorted(self._ls_tree(repo, [r.rstrip("/") for r in roots], recursive=True))

    def _ls_tree(self, repo: str, paths: list[str], *, recursive: bool) -> list[str]:
        checkout = self._ready(repo)
        flags = ["-r"] if recursive else []
        result = self._git.run(
            checkout.root, "ls-tree", *flags, "--full-tree", "--name-only", checkout.ref, "--", *paths
        )
        if not result.ok:
            raise CouldNotLook(f"{repo}: git ls-tree {checkout.ref} failed: {result.text}")
        return [line for line in result.out.splitlines() if line]

    def _ready(self, repo: str) -> Checkout:
        checkout = self._found.get(repo)
        if checkout is None:
            raise CouldNotLook(f"{repo}: not a registry.yaml context")
        if checkout.root is None:
            raise CouldNotLook(f"{repo}: registry.yaml gives no local_path")
        if checkout.fetch_branch == "":
            raise CouldNotLook(f"{repo}: registry.yaml gives no branch")
        if not checkout.root.is_dir():
            raise CouldNotLook(f"{repo}: checkout {checkout.root} is absent")
        if checkout.fetch_branch is not None and repo not in self._fetched:
            fetched = self._git.run(checkout.root, "fetch", "--quiet", "origin", checkout.fetch_branch)
            if not fetched.ok:
                raise CouldNotLook(f"{repo}: git fetch origin {checkout.fetch_branch} failed: {fetched.text}")
            self._fetched.add(repo)
        return checkout
