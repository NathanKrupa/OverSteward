#!/usr/bin/env python
# ABOUTME: Checks a captured reviewer result holds a verdict; recovers the scratch copy of a blind round.
# ABOUTME: Thin shell over oversteward.review_capture — parse argv, print, pick an exit code.

"""Check the adversarial reviewer's captured result (OS#682).

    scripts/review/check_verdict_capture.py <worktree>/.review-verdict-1.md

Run after ``jq -r .result <envelope> > <worktree>/.review-verdict-<N>.md``.
Exit codes:

* ``0`` — a readable ``reviewer-verdict`` fence: PASS, PASS-WITH-FINDINGS or BLOCK.
* ``1`` — a blind round: no fence. ``<worktree>.review`` was recorded, restored
  from HEAD and torn down through the doctor. Relaunch once on the same input.
* ``2`` — stop: the capture could not be read, its fence is malformed, or the
  scratch copy could not be cleared. Nothing here is a pass.
* ``3`` — stop: the relaunch was blind too. Its copy was still cleared.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve the package from THIS checkout's `src/`, ahead of whatever the shared
# venv's editable install points at. Same reasoning as assemble_review_input.py.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.review_capture import (  # noqa: E402
    EXIT_BLIND,
    EXIT_VERDICT,
    check_capture,
)

GATE = "review-capture:"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check_verdict_capture.py")
    parser.add_argument("capture", help="the <worktree>/.review-verdict-<N>.md jq wrote")
    outcome = check_capture(Path(parser.parse_args(argv).capture).absolute())
    if outcome.code == EXIT_VERDICT:
        sys.stdout.write(f"{GATE} verdict captured — {outcome.message}\n")
    elif outcome.code == EXIT_BLIND:
        sys.stderr.write(f"{GATE} BLIND ROUND — {outcome.message}\n")
    else:
        sys.stderr.write(f"{GATE} STOP — {outcome.message}\n")
    return outcome.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
