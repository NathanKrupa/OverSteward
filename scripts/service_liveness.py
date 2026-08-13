#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the service-liveness sweep — what is not running right now.
# ABOUTME: Thin: load registry, call the sweep service, print, map failures to distinct exit codes.

"""Report Railway services that are not running.

The Sentry sweep answers *"what errored"*. Nothing answered *"what is still
running"* — a crashed Railway service emits no Sentry issue, so `embedding` sat
CRASHED for two days while the morning sweep reported inbox zero (OS#353).

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, whether or not anything is down.
* **1** — Railway could not be read. A finding to report, not a quiet morning.
* **2** — nothing was configured to look at.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from oversteward.liveness.check import sweep
from oversteward.liveness.client import RailwayConfigError, RailwayUnavailableError
from oversteward.liveness.config import projects_from_registry
from oversteward.liveness.render import render

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def load_registry() -> dict:
    """Read the one registry this repo owns — a fixed path, never caller-supplied."""
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        report = sweep(projects_from_registry(load_registry()))
    except RailwayConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    except RailwayUnavailableError as exc:
        print(f"ERROR: could not read Railway — {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(render(report))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
