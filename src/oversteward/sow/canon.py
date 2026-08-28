# ABOUTME: INNER readers — canon's own git history, and each target repo's copies as they stand on origin.
# ABOUTME: Every hash is a git blob id produced by git itself, so the same bytes hash alike in any repo.

"""Where the three-way comparison gets its inputs.

The identifier throughout is the **git blob id**, never a hash this code
computes. A blob id is a content address git already assigns identically in
every repository, so canon's history and a pickup repo's `origin` ref can be
compared directly without either side ever handing over its bytes.

Reads are against `origin/<registry branch>` and never a working tree: the
resident checkouts run dozens-to-hundreds of commits stale, which produced both
false drift and false parity when `/sync-status` hashed them (OS#242).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..dev_family import GitRepo, canonical_family, deployed_relpath
from .plan import SYNC_BRANCH_PREFIX, ContextObservation
from .runners import GhCommand, GitCommand

FAMILY_RELDIR = "shared/scripts/dev"


class CanonHistory:
    """Every blob id a canonical family member has carried across this repo's history.

    A repo copy equal to one of them was deployed from canon and left behind; a
    copy equal to none of them is a downstream edit, and is never overwritten.
    This replaces the pinned contract's `reports/manifest.json` baseline, which
    does not exist and never did — a first run against an absent manifest would
    read every deliberate downstream edit as `missing` and clobber it.
    """

    def __init__(self, repo_root: Path, git: GitCommand) -> None:
        self._root = Path(repo_root)
        self._git = git
        self._cache: dict[str, frozenset[str]] = {}

    def relpath(self, member: str) -> str:
        return f"{FAMILY_RELDIR}/{member}"

    def current_blob(self, member: str) -> str | None:
        """The blob id of the canonical file as it stands on disk right now."""
        path = self._root / FAMILY_RELDIR / member
        if not path.is_file():
            return None
        result = self._git.run(self._root, "hash-object", "--", str(path))
        return result.out.strip() if result.ok else None

    def blobs(self, member: str) -> frozenset[str]:
        if member not in self._cache:
            self._cache[member] = frozenset(self._read_blobs(member))
        return self._cache[member]

    def history(self, members: Sequence[str]) -> dict[str, frozenset[str]]:
        return {member: self.blobs(member) for member in members}

    def _read_blobs(self, member: str) -> tuple[str, ...]:
        rel = self.relpath(member)
        log = self._git.run(self._root, "log", "--format=%H", "--", rel)
        if not log.ok:
            return ()
        found = (self._git.run(self._root, "rev-parse", f"{commit}:{rel}") for commit in log.out.split())
        return tuple(result.out.strip() for result in found if result.ok)


def canonical_blobs(repo_root: Path, canonical_shared: Path, git: GitCommand) -> dict[str, str]:
    """Blob id of every canonical family member, keyed by filename."""
    family_dir = Path(canonical_shared) / "scripts" / "dev"
    blobs: dict[str, str] = {}
    for member in canonical_family(canonical_shared):
        result = git.run(repo_root, "hash-object", "--", str(family_dir / member))
        if result.ok:
            blobs[member] = result.out.strip()
    return blobs


def _blob_id(git: GitCommand, repo_root: Path, ref: str, relpath: str) -> str | None:
    result = git.run(repo_root, "rev-parse", f"{ref}:{relpath}")
    return result.out.strip() if result.ok else None


def _unreadable(ctx: dict[str, Any], branch: str) -> ContextObservation:
    return ContextObservation(
        context_id=ctx["id"],
        branch=branch,
        repo_root=ctx.get("local_path"),
        skip_sow=bool(ctx.get("skip_sow")),
        readable=False,
    )


def observe_context(
    ctx: dict[str, Any],
    members: Sequence[str],
    git: GitCommand,
    gh: GhCommand,
    *,
    fetch: bool = True,
) -> ContextObservation:
    """One registry context as it stands on its own origin ref."""
    repo_root = Path(ctx["local_path"])
    branch = ctx.get("branch", "main")
    repo = GitRepo(repo_root)
    if fetch:
        repo.fetch(branch)
    ref = f"origin/{branch}"
    if not repo.has_ref(ref):
        return _unreadable(ctx, branch)
    doctrine = repo.blob(ref, ctx.get("claude_md_path", "CLAUDE.md")) or b""
    return ContextObservation(
        context_id=ctx["id"],
        branch=branch,
        repo_root=str(repo_root),
        skip_sow=bool(ctx.get("skip_sow")),
        readable=True,
        doctrine_text=doctrine.decode("utf-8", errors="replace"),
        deployed={
            member: _blob_id(git, repo_root, ref, deployed_relpath(member)) for member in members
        },
        open_sync_branches=gh.open_sync_branches(repo_root, SYNC_BRANCH_PREFIX),
    )


def observe_registry(
    registry: dict[str, Any],
    members: Sequence[str],
    git: GitCommand,
    gh: GhCommand,
    *,
    only: Sequence[str] = (),
    fetch: bool = True,
) -> tuple[list[ContextObservation], list[str]]:
    """Observations for every selected context, plus the ids that have no local clone.

    A context with no checkout is named rather than silently contributing
    nothing — "not clonable here" and "nothing to do" are different answers.
    """
    observations: list[ContextObservation] = []
    without_checkout: list[str] = []
    for ctx in registry.get("contexts", []):
        if only and ctx.get("id") not in only:
            continue
        local_path = ctx.get("local_path")
        if local_path is None or not Path(local_path).is_dir():
            without_checkout.append(str(ctx.get("id")))
            continue
        observations.append(observe_context(ctx, members, git, gh, fetch=fetch))
    return observations, without_checkout
