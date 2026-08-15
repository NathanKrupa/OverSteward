# ABOUTME: Central reader for registry.yaml — exposes context lookups to Python and shell.
# ABOUTME: Dispatch targets, context ids, and metadata come from here, not hardcoded lists.

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry.yaml"
OWNER = "NathanKrupa"


def load_registry() -> dict[str, Any]:
    with REGISTRY_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def dispatch_targets() -> list[str]:
    """Return context ids marked `dispatch_target: true`, in registry order."""
    data = load_registry()
    return [
        ctx["id"]
        for ctx in data.get("contexts", [])
        if ctx.get("dispatch_target") is True
    ]


def dispatch_target_info(repo_id: str) -> dict[str, Any] | None:
    """Return dispatch metadata for a repo id, or None if not a dispatch target."""
    data = load_registry()
    for ctx in data.get("contexts", []):
        if ctx.get("id") == repo_id and ctx.get("dispatch_target") is True:
            return {
                "id": ctx["id"],
                "subagent": f"{ctx['id']}-dev",
                "repo": ctx.get("repo"),
                "branch": ctx.get("branch"),
                "owner": OWNER,
                "full_name": f"{OWNER}/{ctx['id']}",
            }
    return None


def _cli(argv: list[str]) -> int:
    if not argv:
        print(
            "Usage: python scripts/registry.py {dispatch-targets|info <id>}",
            file=sys.stderr,
        )
        return 2
    cmd = argv[0]
    if cmd == "dispatch-targets":
        for tid in dispatch_targets():
            print(tid)
        return 0
    if cmd == "info":
        if len(argv) < 2:
            print(
                "Usage: python scripts/registry.py info <repo-id>", file=sys.stderr
            )
            return 2
        info = dispatch_target_info(argv[1])
        if info is None:
            print(f"Not a dispatch target: {argv[1]}", file=sys.stderr)
            return 1
        for k, v in info.items():
            print(f"{k}={v}")
        return 0
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
