# ABOUTME: Thin CLI for the dream cycle's transcript reader (list / show).
# ABOUTME: Parses args, calls the oversteward.dream service, formats output. No business logic.

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from oversteward.dream.transcripts import (
    TranscriptMeta,
    default_projects_root,
    enumerate_transcripts,
    find_transcript,
    parse_transcript,
)


def _format_meta(meta: TranscriptMeta) -> str:
    when = datetime.fromtimestamp(meta.mtime).strftime("%Y-%m-%d %H:%M")
    tag = " [worktree]" if meta.is_worktree else ""
    return f"{when}  {meta.repo:16s}  {meta.session_id}{tag}"


def _cmd_list(args: argparse.Namespace) -> int:
    metas = enumerate_transcripts(args.projects_root)
    if args.repo:
        metas = [m for m in metas if m.repo == args.repo]
    for meta in metas:
        print(_format_meta(meta))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    meta = find_transcript(args.projects_root, args.session_id)
    if meta is None:
        print(f"No transcript found for session {args.session_id!r}", file=sys.stderr)
        return 1
    print(parse_transcript(meta.path))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oversteward dream")
    sub = parser.add_subparsers(dest="group", required=True)
    transcripts = sub.add_parser("transcripts", help="inspect session transcripts")
    actions = transcripts.add_subparsers(dest="action", required=True)
    list_p = actions.add_parser("list", help="enumerate discovered transcripts")
    list_p.add_argument("--repo", help="filter to one inferred repo")
    list_p.set_defaults(func=_cmd_list)
    show_p = actions.add_parser("show", help="render one transcript as role-tagged text")
    show_p.add_argument("session_id")
    show_p.set_defaults(func=_cmd_show)
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.projects_root = default_projects_root()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
