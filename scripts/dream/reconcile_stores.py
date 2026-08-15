# ABOUTME: Thin CLI for the one-time split-brain memory reconciliation (OS#195).
# ABOUTME: Parses args, calls oversteward.dream.reconcile, prints the plan/report. Dry-run default; --apply mutates.

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from oversteward.dream.reconcile import reconcile

# The harness path the Claude runtime auto-loads, and the git-backed dream store.
# Both are operator-run defaults; the reconciler itself hardcodes neither.
DEFAULT_HARNESS_PATH = Path("/home/natha/.claude/projects/-home-natha-OverSteward/memory")
DEFAULT_STEWARD_DIR = Path("/home/natha/steward-memory/memory")
DEFAULT_BACKUP_ROOT = Path("/home/natha/steward-memory/reconcile-backups")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile the split-brain memory stores onto steward-memory (OS#195).",
    )
    parser.add_argument("--harness-path", default=str(DEFAULT_HARNESS_PATH))
    parser.add_argument("--steward-dir", default=str(DEFAULT_STEWARD_DIR))
    parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the reconciliation (default: dry run, mutate nothing)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = reconcile(
        Path(args.harness_path),
        Path(args.steward_dir),
        backup_root=Path(args.backup_root),
        apply=args.apply,
    )
    sys.stdout.write(plan.to_report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
