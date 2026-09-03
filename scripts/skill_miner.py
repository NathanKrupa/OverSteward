#!/usr/bin/env python3
# ABOUTME: Thin CLI for the skill miner — repeated Bash sequences in session transcripts become SKILL.md drafts.
# ABOUTME: Parses args, calls oversteward.skills.miner, prints counts. Exit 2 when there was nothing to look at.

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from oversteward.dream.transcripts import default_projects_root
from oversteward.skills.miner import mine_projects_root, write_drafts


def _default_skills_dirs() -> list[Path]:
    return [Path.home() / ".claude" / "skills", Path.cwd() / ".claude" / "skills"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", type=Path, default=default_projects_root())
    parser.add_argument("--repo", help="only transcripts for this repo (e.g. grantspider)")
    parser.add_argument("--since-days", type=int, help="only transcripts modified in the last N days")
    parser.add_argument("--min-sessions", type=int, default=3)
    parser.add_argument("--min-len", type=int, default=2)
    parser.add_argument("--max-len", type=int, default=5)
    parser.add_argument("--limit", type=int, default=20, help="write at most this many drafts")
    parser.add_argument(
        "--out", type=Path, default=Path("reports") / "skill-drafts" / date.today().isoformat()
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        action="append",
        help="existing skills dir to check coverage against (repeatable; default: ~/.claude/skills and ./.claude/skills)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print candidates, write nothing")
    args = parser.parse_args(argv)

    since = time.time() - args.since_days * 86400 if args.since_days else None
    result = mine_projects_root(
        args.projects_root,
        repo=args.repo,
        min_sessions=args.min_sessions,
        min_len=args.min_len,
        max_len=args.max_len,
        since_mtime=since,
    )
    if result.sessions_scanned == 0:
        print(f"no transcripts found under {args.projects_root} (repo={args.repo or 'any'})", file=sys.stderr)
        return 2

    candidates = result.candidates[: args.limit]
    print(f"sessions scanned: {result.sessions_scanned}")
    print(f"runs scanned: {result.runs_scanned}")
    print(f"candidates: {len(result.candidates)} (writing {len(candidates)})")
    for candidate in candidates:
        print(f"  {candidate.support:3d} sessions  {' → '.join(candidate.signatures)}")
    if args.dry_run:
        return 0

    paths = write_drafts(candidates, args.out, skills_dirs=args.skills_dir or _default_skills_dirs())
    print(f"drafts written: {len(paths)} under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
