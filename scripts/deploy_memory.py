# ABOUTME: CLI to mirror the steward-memory store into each machine's ~/.claude memory dirs.
# ABOUTME: Thin wrapper — parses args, calls oversteward.memory_deploy, prints the report.

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


from oversteward.memory_deploy import managed_targets, mirror

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
DEFAULT_SOURCE = "/home/natha/steward-memory/memory"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy the steward-memory store to ~/.claude.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="source memory/ dir")
    parser.add_argument(
        "--targets",
        default="all",
        help="'oversteward', 'all', or a comma-separated list of context ids",
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--prune", action="store_true", help="remove target *.md absent from source")
    parser.add_argument(
        "--pull", action="store_true", help="git -C <source-clone-root> pull before deploying"
    )
    return parser.parse_args(argv)


def select_targets(targets_arg: str, all_targets: dict[str, Path]) -> dict[str, Path]:
    if targets_arg == "all":
        return all_targets
    ids = ["oversteward"] if targets_arg == "oversteward" else targets_arg.split(",")
    return {cid: all_targets[cid] for cid in ids if cid in all_targets}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source)
    if args.pull:
        subprocess.run(["git", "-C", str(source.parent), "pull"], check=True)
    selected = select_targets(args.targets, managed_targets(REGISTRY_PATH))
    reports = {
        cid: mirror(source, target, dry_run=args.dry_run, prune=args.prune)
        for cid, target in selected.items()
    }
    json.dump(reports, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
