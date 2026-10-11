#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the WSL backup gate — may `wsl --export` run right now?
# ABOUTME: Thin: run the readiness probes, print the verdict, exit 0 ready / 1 busy / 2 could not look.

"""Tell Backup-Wsl.ps1 whether the distro is idle enough to export.

Backup-Wsl.ps1 runs this through ``wsl.exe`` before every export and exports only
on exit 0. Exit codes carry meaning and must not be collapsed:

* **0** — ready: every probe read, none of the probed work running.
* **1** — busy: a Claude session, a detached GS long run, an estate job service
  or a container is running.
* **2** — could not look: a probe failed. Never reads as ready.
"""

from __future__ import annotations

import sys

EXIT_COULD_NOT_LOOK = 2


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        # Imported here so a broken venv, or a checkout without the service yet,
        # reads as could-not-look rather than Python's own exit 1, which is "busy".
        from oversteward.backup import readiness

        report = readiness.assess(readiness.default_probes())
        text = readiness.render(report)
    except Exception as exc:  # noqa: BLE001 — a crash must read as could-not-look, never busy
        print(f"COULD NOT LOOK - readiness check crashed: {type(exc).__name__}: {exc}")
        return EXIT_COULD_NOT_LOOK
    print(text)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
