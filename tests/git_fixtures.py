# ABOUTME: Shared helpers that build throwaway git repos whose origin/<branch> ref carries given files.
# ABOUTME: Used by the origin-ref audits' tests (canonical family, hook registration).

from __future__ import annotations

import subprocess


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(root, files, branch="main", links=None):
    """Create a git repo whose origin/<branch> ref carries `files` and symlinks `links`."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, target in (links or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(root, "update-ref", f"refs/remotes/origin/{branch}", head)
    return root
