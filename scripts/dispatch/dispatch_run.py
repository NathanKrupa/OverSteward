#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — is a dispatched agent held on a confirmation prompt, and was its duration measured?
# ABOUTME: Thin: parse args, call oversteward.dispatch_run, print. Exit codes are in the module docstring.
"""Read dispatched agents' transcripts for what their own reports cannot say (OS#674).

``prompts`` — is any subagent waiting on an ``ask`` prompt nobody will answer?

* **0** — measured: no prompt held past ``--warn-min`` (prints the count checked).
* **3** — alert: at least one prompt held; each is named with its transcript.
* **1** — a transcript could not be read.
* **2** — nothing to look at: no subagent transcript in the window.

``report`` — was the YAML report's ``duration_seconds`` measured?

* **0** — it equals ``ended_at - started_at``, and the transcript's span if given.
* **1** — it does not; each reason is printed.
* **2** — the report or the transcript could not be read.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from oversteward import dispatch_run

DEFAULT_ROOT = Path.home() / ".claude" / "projects"


def _prompts(args: argparse.Namespace) -> int:
    def find(now: datetime) -> list[Path]:
        if args.transcript:
            return [Path(p) for p in args.transcript]
        return dispatch_run.recent_transcripts(args.root, now, args.window_hours)

    try:
        if args.watch:
            result = dispatch_run.watch(find, args.warn_min, args.for_min, args.poll_sec)
        else:
            now = datetime.now(UTC)
            result = dispatch_run.sweep(find(now), now, args.warn_min)
    except dispatch_run.TranscriptUnreadable as error:
        print(f"could not read a transcript: {error}")
        return 1
    if result.checked == 0:
        print(f"nothing to look at: no subagent transcript under {args.root}")
        return 2
    now = datetime.now(UTC)
    for held in result.blocked:
        print(
            f"BLOCKED {held.transcript}: tool call {held.tool_use_id} has waited "
            f"{held.age_min(now):.0f}m on a confirmation prompt since "
            f"{held.asked_at:%Y-%m-%dT%H:%M:%SZ} ({held.reason})"
        )
    print(f"{len(result.blocked)} held prompt(s) across {result.checked} transcript(s) checked")
    return 3 if result.blocked else 0


def _report(args: argparse.Namespace) -> int:
    try:
        report = dispatch_run.report_from_text(args.report.read_text(encoding="utf-8"))
        span = None
        if args.transcript:
            span = dispatch_run.transcript_span_s(dispatch_run.read_entries(args.transcript))
    except (OSError, ValueError, dispatch_run.TranscriptUnreadable) as error:
        print(f"could not read: {error}")
        return 2
    problems = dispatch_run.duration_problems(report, span)
    for problem in problems:
        print(f"NOT MEASURED: {problem}")
    if not problems:
        print(f"measured: duration_seconds {report['duration_seconds']} matches its stamps")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    prompts = sub.add_parser("prompts", help="find a subagent held on a confirmation prompt")
    prompts.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    prompts.add_argument("--transcript", action="append", help="check only this transcript")
    prompts.add_argument("--warn-min", type=float, default=10.0)
    prompts.add_argument("--window-hours", type=float, default=24.0)
    prompts.add_argument("--watch", action="store_true", help="poll until held or --for-min")
    prompts.add_argument("--for-min", type=float, default=480.0)
    prompts.add_argument("--poll-sec", type=float, default=60.0)
    prompts.set_defaults(run=_prompts)
    report = sub.add_parser("report", help="check a report's duration_seconds against its stamps")
    report.add_argument("report", type=Path, help="file holding the agent's YAML report")
    report.add_argument("--transcript", type=Path, help="the agent's transcript, for its span")
    report.set_defaults(run=_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
