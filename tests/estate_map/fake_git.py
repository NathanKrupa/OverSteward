# ABOUTME: An in-memory stand-in for `git fetch` and `git ls-tree` over a fixed set of tracked files.
# ABOUTME: Records every call so a test can prove which ref was read and that a fetch preceded it.

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from oversteward.sow.runners import CommandResult


class FakeGit:
    def __init__(self, trees: dict[str, Iterable[str]], *, fetch_ok: bool = True) -> None:
        #: ref -> tracked file paths at that ref
        self.trees = {ref: set(files) for ref, files in trees.items()}
        self.fetch_ok = fetch_ok
        self.calls: list[tuple[str, ...]] = []

    def run(self, cwd: Path, *args: str) -> CommandResult:
        self.calls.append((str(cwd), *args))
        if args[0] == "fetch":
            return CommandResult(self.fetch_ok, "", "" if self.fetch_ok else "fatal: no remote")
        if args[0] == "ls-tree":
            return self._ls_tree(list(args[1:]))
        raise AssertionError(f"unexpected git call {args}")

    def _ls_tree(self, args: list[str]) -> CommandResult:
        recursive = "-r" in args
        split = args.index("--")
        ref = [a for a in args[:split] if not a.startswith("-")][0]
        paths = args[split + 1 :]
        if ref not in self.trees:
            return CommandResult(False, "", f"fatal: Not a valid object name {ref}")
        files = self.trees[ref]
        if recursive:
            out = {f for f in files for path in paths if f == path or f.startswith(path + "/")}
        else:
            out = {e for e in _entries(files) if _shown(e, paths)}
        return CommandResult(True, "".join(f"{p}\n" for p in sorted(out)), "")


def _entries(files: Iterable[str]) -> set[str]:
    """Every file and every directory above one: the entries a tree walk can meet."""
    found: set[str] = set()
    for f in files:
        parts = f.split("/")
        found.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return found


def _shown(entry: str, paths: list[str]) -> bool:
    """Real `git ls-tree` without `-r`: it descends into any directory that holds a deeper
    pathspec and then prints that directory's matching children, never the directory itself."""

    def descends(e: str) -> bool:
        return any(p.startswith(e + "/") for p in paths)

    matches = any(entry == p or entry.startswith(p + "/") for p in paths)
    parts = entry.split("/")
    ancestors = ("/".join(parts[:i]) for i in range(1, len(parts)))
    return matches and not descends(entry) and all(descends(a) for a in ancestors)
