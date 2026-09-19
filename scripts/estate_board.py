#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the Estate Board — reads GitHub, assembles the board, writes the page.
# ABOUTME: Thin: load registry, call the services, print a summary, map failures to distinct exit codes.

"""Build the Estate Board page from every dispatch-target repository.

The board shows what wants a decision from Nathan — agents waiting on an
answer, epics whose health asks for a ruling — plus counts. The page is
written to ``--out`` and published as the Estate Board artifact by the
session; nothing here is stored anywhere but GitHub.

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, whether or not anything waits.
* **1** — GitHub could not be read (``gh`` failed, or a page filled its limit).
* **2** — no repository is marked ``dispatch_target`` in the registry.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.board.assemble import assemble
from oversteward.board.client import GhError, read_estate
from oversteward.board.config import repos_from_registry
from oversteward.board.render import render

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
DEFAULT_OUT = REPO_ROOT / "data" / "estate_board.html"

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def load_registry() -> dict:
    """Read the one registry this repo owns — a fixed path, never caller-supplied."""
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the page")
    args = parser.parse_args(argv)

    try:
        repos = repos_from_registry(load_registry())
    except ValueError as exc:
        print(f"ERROR: registry.yaml — {exc}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    if not repos:
        print("ERROR: no dispatch_target repositories in registry.yaml", file=sys.stderr)
        return EXIT_MISCONFIGURED
    try:
        issues_by_repo = read_estate(repos)
    except GhError as exc:
        print(f"ERROR: could not read GitHub — {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK

    report = assemble(issues_by_repo, now=datetime.now(UTC))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report), encoding="utf-8")

    read = sum(len(v) for v in issues_by_repo.values())
    print(
        f"{len(repos)} repositories · {read} issues read · {len(report.decisions)} decisions → {args.out}"
    )
    for d in report.decisions:
        stale = " STALE" if d.stale else ""
        print(f"  {d.repo} {d.ref:<26} {d.age_days:>4}d{stale}  {d.ask}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
