#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the scratchpad janitor — prune dead sessions' ~/.claude/tmp dirs.
# ABOUTME: Thin: parse flags, run the service, print the report, exit 0 measured / 1 failed / 2 not configured.

"""Report (and with ``--apply``, delete) finished sessions' scratchpad dirs.

Dry run by default; scratchpad-janitor.service passes ``--apply``.

Exit codes carry meaning and must not be collapsed:

* **0** — measured: the report is complete, and under ``--apply`` every prune finished.
* **1** — could not look (the ``/proc`` scan is blind, a dir is unreadable), a
  prune was partial, or the run crashed.
* **2** — not configured: the root is missing, not a directory or a symlink, or
  ``--days`` is below 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_FAILED = 1


def _parse(argv: list[str]) -> argparse.Namespace:
    from oversteward.janitor import scratchpad

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=scratchpad.DEFAULT_DAYS)
    parser.add_argument("--apply", action="store_true", help="delete; the default only reports")
    parser.add_argument("--root", type=Path, default=scratchpad.DEFAULT_ROOT)
    parser.add_argument("--proc", type=Path, default=scratchpad.DEFAULT_PROC)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        # Imported here so a broken venv reads as a failure with a reason, not a bare traceback.
        from oversteward.janitor import scratchpad

        args = _parse(sys.argv[1:] if argv is None else argv)
        config = scratchpad.JanitorConfig(
            root=args.root, proc=args.proc, days=args.days, apply=args.apply
        )
        outcome = scratchpad.run_janitor(config)
    except Exception as exc:  # noqa: BLE001 — a crash must read as failed, never ok
        print(f"FAILED - scratchpad janitor crashed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    print(scratchpad.render(outcome), flush=True)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
