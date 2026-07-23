# ABOUTME: Read-only state extraction across all registry contexts (H2-3).
# ABOUTME: Hashes CLAUDE.md managed blocks, settings, hooks, and shared deploy trees. No writes.

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

MANAGED_BLOCK_RE = re.compile(
    r"<!-- \[oversteward:managed(?: \| synced: (?P<synced>[0-9-]+))?\] -->\n"
    r"(?P<text>.*?)"
    r"<!-- \[oversteward:managed:end\] -->",
    re.DOTALL,
)
LOCAL_BLOCK_MARKER = "<!-- [oversteward:local] -->"

# Per-target mutable files: deployed copies legitimately diverge from canonical.
MUTABLE_SHARED_FILES = {"inbox.md"}

HOOK_RELPATH = ".claude/hooks/guard_main_worktree.py"
NEW_SESSION_RELPATH = "scripts/dev/new-session.sh"
WITH_TEST_ENV_RELPATH = "scripts/dev/with_test_env.py"
# The Tier-1 secret-scan gate script (scripts/dev/secret_scan.py).
SCAN_SCRIPT_RELPATH = "scripts/dev/secret_scan.py"
GITLEAKSIGNORE_RELPATH = ".gitleaksignore"
SETTINGS_RELPATH = ".claude/settings.json"
CANONICAL_DEV_FILES = (
    "guard_main_worktree.py",
    "new-session.sh",
    "with_test_env.py",
    "secret_scan.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_or_none(path: Path) -> str | None:
    return _sha256(path) if path.is_file() else None


def extract_managed_block(text: str) -> dict[str, Any]:
    """Parse the [oversteward:managed] block out of a CLAUDE.md body."""
    match = MANAGED_BLOCK_RE.search(text)
    if match is None:
        return {"present": False, "synced": None, "text": None}
    return {"present": True, "synced": match.group("synced"), "text": match.group("text")}


def _gather_claude_md(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False}
    text = path.read_text(encoding="utf-8")
    return {
        "exists": True,
        "sha256": _sha256(path),
        "managed": extract_managed_block(text),
        "local_block_present": LOCAL_BLOCK_MARKER in text,
    }


def gather_context(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extract one registry context's on-disk governance state."""
    base = {
        "id": ctx["id"],
        "type": ctx.get("type"),
        "skip_sow": ctx.get("skip_sow", False),
        "soul": ctx.get("soul"),
        "soul_in_local": ctx.get("soul_in_local", False),
    }
    local_path = ctx.get("local_path")
    if local_path is None or not Path(local_path).is_dir():
        return {**base, "reachable": False}
    root = Path(local_path)
    return {
        **base,
        "reachable": True,
        "claude_md": _gather_claude_md(root / ctx["claude_md_path"]),
        "settings_sha256": _sha256_or_none(root / SETTINGS_RELPATH),
        "hook_sha256": _sha256_or_none(root / HOOK_RELPATH),
        "new_session_sha256": _sha256_or_none(root / NEW_SESSION_RELPATH),
        "with_test_env_sha256": _sha256_or_none(root / WITH_TEST_ENV_RELPATH),
        "secret_scan_sha256": _sha256_or_none(root / SCAN_SCRIPT_RELPATH),
        "gitleaksignore_present": (root / GITLEAKSIGNORE_RELPATH).is_file(),
    }


def gather_shared_tree(root: Path) -> dict[str, str] | None:
    """Hash every file under a shared tree, keyed by POSIX relpath.

    Returns None when the tree doesn't exist (a missing deploy target is a
    finding for diff, not an error here). Bytecode caches and per-target
    mutable files are excluded.
    """
    if not root.is_dir():
        return None
    tree: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or rel.name in MUTABLE_SHARED_FILES:
            continue
        tree[rel.as_posix()] = _sha256(path)
    return tree


def gather_state(
    registry: dict[str, Any],
    canonical_shared: Path,
    deploy_targets: dict[str, Path],
) -> dict[str, Any]:
    """Assemble the full read-only snapshot: contexts + canonical shared + deploy targets."""
    canonical_tree = gather_shared_tree(canonical_shared) or {}
    canonical_dev = {
        name: canonical_tree.get(f"scripts/dev/{name}") for name in CANONICAL_DEV_FILES
    }
    return {
        "contexts": [gather_context(ctx) for ctx in registry.get("contexts", [])],
        "canonical_shared": canonical_tree,
        "canonical_dev": canonical_dev,
        "deploy_targets": {
            name: gather_shared_tree(path) for name, path in deploy_targets.items()
        },
    }


def default_paths() -> dict[str, Any]:
    """Factory for the real estate layout. The only place real paths live."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    return {
        "repo_root": repo_root,
        "canonical_shared": repo_root / "shared",
        "deploy_targets": {
            "wsl": Path.home() / ".claude" / "shared",
            "windows": Path("/mnt/c/Users/natha/.claude/shared"),
        },
    }
