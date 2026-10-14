#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the backup health sweep — restic snapshot, verified restore, export, E: free.
# ABOUTME: Thin: parse path overrides, run the service, print four rows; a crash exits 1, never 0.

"""Report whether the restic home backup and the full WSL export are current.

The sixth session-start sweep. The daily backup and the monthly export each
write their own success marker, but nothing read those markers back: a backup
that stopped running would sit silent until the day it was needed (OS#583).

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, whether or not a row is RED.
* **1** — something could not be read (the export drive not mounted, restic or
  systemctl failed, unparseable output), or the sweep crashed.
* **2** — not configured: restic, the key or the repository is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_COULD_NOT_READ = 1


def _parse(argv: list[str]) -> argparse.Namespace:
    from oversteward.backup import health

    defaults = health.BackupHealthConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=defaults.repo)
    parser.add_argument("--key", type=Path, default=defaults.key)
    parser.add_argument("--restic", type=Path, default=defaults.restic)
    parser.add_argument("--state-dir", type=Path, default=defaults.state_dir)
    parser.add_argument("--mirror-dir", type=Path, default=None)
    parser.add_argument("--export-dir", type=Path, default=defaults.export_dir)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, run=None) -> int:
    try:
        # Imported here so a broken venv reads as could-not-read with a reason, not a traceback.
        from oversteward.backup import health

        args = _parse(sys.argv[1:] if argv is None else argv)
        config = health.BackupHealthConfig(
            repo=args.repo,
            key=args.key,
            restic=args.restic,
            state_dir=args.state_dir,
            mirror_dir=args.mirror_dir,
            export_dir=args.export_dir,
        )
        report = health.check_health(config, run=run or health.run_command)
    except Exception as exc:  # noqa: BLE001 — a crash must read as could-not-read, never measured
        print(f"COULD NOT READ - backup health sweep crashed: {type(exc).__name__}: {exc}")
        return EXIT_COULD_NOT_READ
    print(health.render(report), flush=True)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
