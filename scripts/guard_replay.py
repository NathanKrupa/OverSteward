#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — replay the destructive-command gate over recorded session Bash commands.
# ABOUTME: Thin: parse args, call oversteward.guard_replay, print counts. Read-only; exit codes below.
"""Replay check_destructive_command.py over the Bash commands sessions recorded (OS#192).

Prints counts only: no command, path or project name reaches stdout. ``--rows``
writes one JSON line per distinct command the hook held or crashed on, command
text included, so keep that file outside any repository.

* **0** — measured.
* **1** — could not read: a missing root, hook, registry or labels file, a
  transcript it rejected (named on stderr; the rest are still measured), or a
  hook ``error`` outcome.
* **2** — nothing to look at: no Bash command in the window.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from oversteward import guard_replay

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_HOOK = REPO / "shared" / "scripts" / "dev" / "check_destructive_command.py"
DEFAULT_REGISTRY = REPO / "registry.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Claude Code projects dir")
    parser.add_argument("--since-days", type=float, default=30.0)
    parser.add_argument("--hook", type=Path, default=DEFAULT_HOOK, help="the hook file to replay")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--labels", type=Path, help="JSON Lines of key, verdict and class")
    parser.add_argument("--rows", type=Path, help="write the flagged rows here (private)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, labels = guard_replay.measure(
            args.root, args.since_days, time.time(), args.hook, args.registry, args.labels
        )
    except guard_replay.ReplayUnreadable as error:
        print(f"could not look: {error}", file=sys.stderr)
        return 1
    for problem in result.unreadable:
        print(f"unreadable transcript: {problem}", file=sys.stderr)
    print(guard_replay.summary(result, labels, args.hook.name, args.since_days))
    if args.rows is not None:
        guard_replay.write_rows(result, labels, args.rows)
    return guard_replay.exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
