# ABOUTME: Audits the canonical shared/scripts/dev/ byte-copy family across every managed repo.
# ABOUTME: Compares canonical bytes against each repo's origin ref — never the stale working tree.

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FAMILY_SUBDIR = ("scripts", "dev")

PRESENT = "present-identical"
DRIFTED = "drifted"
ABSENT = "absent"
ABSENT_REFERENCED = "absent-but-doctrine-referenced"

# Members that deploy as registered Claude hooks rather than into <repo>/scripts/dev/.
HOOK_MEMBERS = frozenset(
    {
        "guard_main_worktree.py",
        "guard_neon.py",
        "guard_shared_venv.py",
        "check_destructive_command.py",
    }
)


@dataclass(frozen=True)
class OriginFamily:
    """One repo's deployed family copies, as they stand on its origin ref."""

    available: bool
    fetched: bool
    deployed: dict[str, str | None] = field(default_factory=dict)
    doctrine_text: str = ""


@dataclass(frozen=True)
class RepoFamilyStatus:
    """Every canonical member's status in one managed repo."""

    context_id: str
    branch: str
    available: bool
    fetched: bool
    members: dict[str, str] = field(default_factory=dict)


def _git(root: Path, *args: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def _sha_or_none(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


class GitRepo:
    """Reads one repo's committed refs. Never touches its working tree or index."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def fetch(self, branch: str) -> bool:
        """Refresh a remote-tracking ref. Refs only — no working-tree or index change."""
        return _git(self._root, "fetch", "--quiet", "origin", branch) is not None

    def has_ref(self, ref: str) -> bool:
        return _git(self._root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None

    def blob(self, ref: str, relpath: str) -> bytes | None:
        return _git(self._root, "cat-file", "blob", f"{ref}:{relpath}")


def deployed_relpath(member: str) -> str:
    """Where a canonical family member lands inside a pickup repo."""
    if member.startswith("."):
        return member
    if member in HOOK_MEMBERS:
        return f".claude/hooks/{member}"
    if member.startswith("test_"):
        return f"tests/dev/{member}"
    return f"scripts/dev/{member}"


def canonical_family(canonical_shared: Path) -> dict[str, str]:
    """Hash every member of canonical ``shared/scripts/dev/``, keyed by filename."""
    root = canonical_shared.joinpath(*FAMILY_SUBDIR)
    if not root.is_dir():
        return {}
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def classify_member(canonical_sha: str, deployed_sha: str | None, doctrine_referenced: bool) -> str:
    """One member's status in one repo.

    Absence is split in two: a member the repo's doctrine already tells agents to
    use is a broken instruction, not a not-yet-adopted file.
    """
    if deployed_sha is None:
        return ABSENT_REFERENCED if doctrine_referenced else ABSENT
    return PRESENT if deployed_sha == canonical_sha else DRIFTED


def classify_repo_family(
    canonical: dict[str, str], deployed: dict[str, str | None], doctrine_text: str
) -> dict[str, str]:
    """Status for every canonical member against one repo's observed copies."""
    return {
        member: classify_member(sha, deployed.get(member), member in doctrine_text)
        for member, sha in canonical.items()
    }


def read_origin_family(
    repo_root: Path,
    branch: str,
    members: Iterable[str],
    claude_md_path: str,
    fetch: bool = True,
) -> OriginFamily:
    """Read one repo's deployed family copies out of ``origin/<branch>``.

    The resident checkouts run stale, so the working tree is never consulted —
    comparing against it produces both false drift and false parity.
    """
    git = GitRepo(repo_root)
    fetched = git.fetch(branch) if fetch else False
    ref = f"origin/{branch}"
    if not git.has_ref(ref):
        return OriginFamily(available=False, fetched=fetched)
    doctrine = git.blob(ref, claude_md_path) or b""
    return OriginFamily(
        available=True,
        fetched=fetched,
        deployed={
            member: _sha_or_none(git.blob(ref, deployed_relpath(member))) for member in members
        },
        doctrine_text=doctrine.decode("utf-8", errors="replace"),
    )


def _status_for_context(
    ctx: dict[str, Any], canonical: dict[str, str], fetch: bool
) -> RepoFamilyStatus | None:
    local_path = ctx.get("local_path")
    if local_path is None or not Path(local_path).is_dir():
        return None
    branch = ctx.get("branch", "main")
    observed = read_origin_family(
        Path(local_path),
        branch,
        canonical,
        ctx.get("claude_md_path", "CLAUDE.md"),
        fetch=fetch,
    )
    return RepoFamilyStatus(
        context_id=ctx["id"],
        branch=branch,
        available=observed.available,
        fetched=observed.fetched,
        members=classify_repo_family(canonical, observed.deployed, observed.doctrine_text)
        if observed.available
        else {},
    )


def gather_family_status(
    registry: dict[str, Any], canonical_shared: Path, fetch: bool = True
) -> list[RepoFamilyStatus]:
    """Family status for every registry context with a local clone to read origin from."""
    canonical = canonical_family(canonical_shared)
    statuses = (
        _status_for_context(ctx, canonical, fetch) for ctx in registry.get("contexts", [])
    )
    return [status for status in statuses if status is not None]


def format_family_table(rows: list[RepoFamilyStatus]) -> list[str]:
    """Render the family status matrix as one line per repo x member."""
    lines: list[str] = []
    for row in rows:
        header = f"{row.context_id} (origin/{row.branch})"
        if not row.available:
            lines.append(f"{header}: origin ref unreadable — not checked")
            continue
        lines.append(f"{header}:")
        width = max((len(member) for member in row.members), default=0)
        lines.extend(
            f"  {member:<{width}}  {status}" for member, status in sorted(row.members.items())
        )
    return lines
