#!/usr/bin/env python3
# ABOUTME: Stop hook — enqueue the ending session's transcript for the dream cycle and surface a reminder.
# ABOUTME: Never runs the cycle in-hook (work runs in-session); idempotent vs the ledger; always fails open.
"""Enqueue-on-stop for the convergent dream cycle (design §4, OverSteward #114).

When a Claude Code session ends, this ``Stop`` hook flags the just-finished
transcript so the next ``/dream`` run (sign-off, or the cron backstop) consolidates
it — catching sessions Nathan never explicitly signs off. It does the cheap thing
only: hash the ending transcript, enqueue it if it is neither already consolidated
(the processed-transcript ledger) nor already queued, and print a one-line reminder
to run ``/dream``. The consolidation itself runs IN-SESSION, never inside the hook.

Stdlib + the stdlib-only ``oversteward.dream.ledger`` only — it is launched by the
system ``python3`` (no project venv, no yaml). Any failure fails OPEN (exit 0): a
broken reminder must never block a session from stopping.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# This hook lives at <repo>/.claude/hooks/; the package is under <repo>/src.
# Reason: the sibling scripts under scripts/ dropped this bootstrap because
# they run through `uv run` and import the installed package. This hook does
# not — .claude/settings.json invokes it as bare `python3`, outside the venv,
# so the path insert is the only way it finds oversteward. Keep it.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))  # noqa: STRUCT-010


def _queue_path() -> Path:
    override = os.environ.get("OVERSTEWARD_DREAM_QUEUE")
    if override:
        return Path(override)
    from oversteward.dream.ledger import DEFAULT_QUEUE_PATH

    return DEFAULT_QUEUE_PATH


def _ledger_path() -> Path:
    override = os.environ.get("OVERSTEWARD_DREAM_LEDGER")
    if override:
        return Path(override)
    from oversteward.dream.ledger import default_ledger_path

    return default_ledger_path(_REPO_ROOT)


def _enqueue(session_id: str, transcript_path: str) -> bool:
    from oversteward.dream.ledger import (
        ProcessedLedger,
        enqueue_transcript,
        transcript_hash,
    )

    path = Path(transcript_path)
    if not path.is_file():
        return False
    ledger = ProcessedLedger(_ledger_path())
    return enqueue_transcript(
        _queue_path(),
        ledger,
        session_id=session_id,
        path=transcript_path,
        content_hash=transcript_hash(path),
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable Stop event → fail open
        return 0
    try:
        session_id = str(event.get("session_id", "") or "")
        transcript_path = str(event.get("transcript_path", "") or "")
        if not transcript_path:
            return 0
        if _enqueue(session_id, transcript_path):
            sys.stderr.write(
                "[dream] this session's transcript is queued for consolidation — "
                "run /dream to drain the queue (memory only, never code).\n"
            )
    except Exception:  # any failure must not block the session from stopping
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
