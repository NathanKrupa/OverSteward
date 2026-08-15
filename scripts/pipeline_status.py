# ABOUTME: OUTER entrypoint for /pipeline-status — reads vintner.corpus_funnel_v and prints the funnel report.
# ABOUTME: Thin: read DSN, read view, load snapshot, build report, render, print, persist snapshot. No logic here.

from __future__ import annotations

import sys
from pathlib import Path


from oversteward.vintner.funnel import build_report, snapshot_counts
from oversteward.vintner.reader import (
    VintnerConfigError,
    read_corpus_funnel,
    research_dsn,
)
from oversteward.vintner.render import render
from oversteward.vintner.snapshot import load_snapshot, save_snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / ".claude" / "skills" / "pipeline-status" / "state.json"


def main(argv: list[str]) -> int:
    try:
        dsn = research_dsn()
    except VintnerConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        rows = read_corpus_funnel(dsn)
    except Exception as exc:  # noqa: BLE001 — surface any live-read failure to the operator
        print(f"ERROR: could not read vintner.corpus_funnel_v: {exc}", file=sys.stderr)
        return 1

    previous = load_snapshot(SNAPSHOT_PATH)
    report = build_report(rows, previous=previous)
    print(render(report), end="")

    save_snapshot(
        SNAPSHOT_PATH,
        snapshot_counts(report),
        report.generated_at.isoformat(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
