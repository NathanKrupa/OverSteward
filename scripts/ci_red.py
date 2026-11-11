#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the ci-red sweep — lists every open ci-red issue, records verdicts.
# ABOUTME: Thin: parse args, call the ci_red service, print; exit 0 measured, 1 unreadable, 2 none.

"""What has CI turned red across the dispatch targets, and is each red resolved?

* **0** — measured: every target was read (open ci-red issues may remain).
* **1** — could not read: a repository's issues, its ``ci.yml`` ref, or a
  verdict's ref. Nothing is written — not the snapshot, not the ledger.
* **2** — nothing to look at: the registry names no dispatch target. ``record``
  also exits 2 on a verdict that does not verify, having closed nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.ci_red.render import render_record, render_sweep
from oversteward.ci_red.sources import (
    GithubCiRed,
    RefReader,
    Target,
    targets_from_registry,
    watched,
)
from oversteward.dev_family import GitRepo
from oversteward.ci_red.triage import (
    VERDICTS,
    CiRedSource,
    CiRedUnreadable,
    VerdictError,
    VerdictStore,
    read_estate,
    record,
    sweep,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
LEDGER_DIR = REPO_ROOT / "data" / "ci_red"

EXIT_COULD_NOT_READ = 1
EXIT_NOTHING_TO_LOOK_AT = 2


def load_targets() -> list[Target]:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return targets_from_registry(yaml.safe_load(handle) or {})


def default_store() -> VerdictStore:
    return VerdictStore(LEDGER_DIR / "ledger.jsonl", LEDGER_DIR / "pending.json")


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _cmd_sweep(args, targets, source, is_watched, store) -> int:
    try:
        readings = read_estate(targets, source, is_watched)
        result = sweep(readings, store, source, targets)
    except CiRedUnreadable as exc:
        return _fail(f"could not read — {exc}", EXIT_COULD_NOT_READ)
    store.save_pending(i.key for r in readings for i in r.issues)
    print(render_sweep(result), end="")
    return 0


def _cmd_record(args, targets, source, _is_watched, store) -> int:
    try:
        ruling = record(
            store, source, targets, args.issue, args.verdict, args.ref, datetime.now(UTC)
        )
    except CiRedUnreadable as exc:
        return _fail(f"could not verify — {exc}; nothing closed", EXIT_COULD_NOT_READ)
    except VerdictError as exc:
        return _fail(f"{exc}; nothing closed", EXIT_NOTHING_TO_LOOK_AT)
    print(render_record(ruling))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci_red.py",
        description="Sweep every dispatch target's open ci-red issues; record a verdict per issue.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    swp = sub.add_parser("sweep", help="List open ci-red issues and each repo's watch state.")
    swp.set_defaults(func=_cmd_sweep)
    rec = sub.add_parser("record", help="Verify a ref, then rule on (and maybe close) one issue.")
    rec.add_argument("issue", help="The key the sweep printed, e.g. grantspider#3530")
    rec.add_argument("verdict", choices=VERDICTS)
    rec.add_argument(
        "--ref",
        required=True,
        help=(
            "fixed: <repo>#<pr>; unmerged: <red pr>; green: <run id>; "
            "fixed-in-place: <run id>; filed|known: <repo>#<n>"
        ),
    )
    rec.set_defaults(func=_cmd_record)
    return parser


def main(
    argv: list[str],
    *,
    targets_loader: Callable[[], list[Target]] = load_targets,
    source: CiRedSource | None = None,
    repo_factory: Callable[[Path], RefReader] = GitRepo,
    store: VerdictStore | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = targets_loader()
    except ValueError as exc:
        return _fail(f"not configured — {exc}", EXIT_NOTHING_TO_LOOK_AT)
    if not targets:
        return _fail("the registry names no dispatch target", EXIT_NOTHING_TO_LOOK_AT)
    return args.func(
        args,
        targets,
        source if source is not None else GithubCiRed(),
        lambda target: watched(target, repo_factory=repo_factory),
        store if store is not None else default_store(),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
