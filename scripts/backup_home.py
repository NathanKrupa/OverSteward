#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the daily restic backup of /home — snapshot, prune, verified restore.
# ABOUTME: Thin: parse path overrides, run the service, print the verdict, exit 0 ok / 1 failed / 2 not configured.

"""Run the daily live backup of ``/home/natha`` (home-backup.service calls this).

Exit codes carry meaning and must not be collapsed:

* **0** — snapshot taken, retention applied, a restored file matched its source,
  and ``restic.last-ok`` was written.
* **1** — a step failed or the run crashed; no marker written.
* **2** — not configured (key, repository, restic or source missing); nothing ran.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_FAILED = 1


def _parse(argv: list[str]) -> argparse.Namespace:
    from oversteward.backup import home

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=home.DEFAULT_SOURCE)
    parser.add_argument("--repo", type=Path, default=home.DEFAULT_REPOSITORY)
    parser.add_argument("--password-file", type=Path, default=home.DEFAULT_PASSWORD_FILE)
    parser.add_argument("--state-dir", type=Path, default=home.DEFAULT_STATE_DIR)
    parser.add_argument("--restic", type=Path, default=home.DEFAULT_RESTIC)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        # Imported here so a broken venv reads as a failure with a reason, not a bare traceback.
        from oversteward.backup import home

        args = _parse(sys.argv[1:] if argv is None else argv)
        config = home.HomeBackupConfig(
            source=args.source,
            repository=args.repo,
            password_file=args.password_file,
            state_dir=args.state_dir,
            restic=args.restic,
        )
        outcome = home.run_backup(config)
    except Exception as exc:  # noqa: BLE001 — a crash must read as failed, never ok
        print(f"FAILED - home backup crashed: {type(exc).__name__}: {exc}")
        return EXIT_FAILED
    print(home.render(outcome), flush=True)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
