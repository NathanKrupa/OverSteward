#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for /stage-health — sweeps GrantSpider's stage-health ledger, records verdicts.
# ABOUTME: Thin: parse args, call the stage-health service, print; the producer's exit code passes through.

"""Is every GrantSpider pipeline stage still doing its work?

Reads ``grantspider dq health --json`` and asks for a verdict on every RED row.
The producer's exit code is handed back unchanged, and must not be collapsed:

* **0** — measured. The ledger was read; the verdict may still be RED.
* **1** — could not read: the producer's database, its thresholds, the
  document itself (an unknown ``schema`` included), or a verdict's issue.
* **2** — no stage_health rows in the window: the asset is not running. Also
  the registry naming no GrantSpider checkout, or an impossible ``record``.

A local read that cannot reach the database is retried once inside the
production service via ``railway ssh``; the headline names the route that
answered, and that route's own failure is exit 1, never 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.stage_health.render import (
    render_no_rows,
    render_record,
    render_sweep,
    render_unreadable,
)
from oversteward.stage_health.sources import (
    GithubIssueStates,
    GrantspiderHealthCli,
    IssueStateUnavailableError,
    ProducerConfigError,
    ProducerUnavailableError,
    RailwayHealthSsh,
    checkout_from_registry,
)
from oversteward.stage_health.triage import (
    STATUS_MEASURED,
    STATUS_NO_ROWS,
    VERDICTS,
    HealthReader,
    IssueStates,
    StageHealthUnreadable,
    VerdictError,
    VerdictStore,
    record,
    sweep,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
LEDGER_DIR = REPO_ROOT / ".claude" / "skills" / "stage-health"

EXIT_COULD_NOT_READ = 1
EXIT_MISCONFIGURED = 2


def default_store() -> VerdictStore:
    return VerdictStore(LEDGER_DIR / "ledger.jsonl", LEDGER_DIR / "pending.json")


def default_producer(days: int | None) -> HealthReader:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        registry = yaml.safe_load(handle) or {}
    checkout = checkout_from_registry(registry)
    return HealthReader(
        GrantspiderHealthCli(checkout, days=days), RailwayHealthSsh(checkout, days=days)
    )


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _cmd_sweep(args, producer_factory: Callable, store: VerdictStore, issues: IssueStates) -> int:
    try:
        producer = producer_factory(args.days)
    except ProducerConfigError as exc:
        return _fail(f"not configured — {exc}", EXIT_MISCONFIGURED)
    try:
        document = producer.read()
    except (ProducerUnavailableError, StageHealthUnreadable) as exc:
        return _fail(f"could not read stage health — {exc}", EXIT_COULD_NOT_READ)
    if document.status == STATUS_NO_ROWS:
        print(render_no_rows(document))
        return document.exit_code
    if document.status != STATUS_MEASURED:
        return _fail(render_unreadable(document), document.exit_code)
    try:
        result = sweep(document, store, issues)
    except (IssueStateUnavailableError, StageHealthUnreadable) as exc:
        return _fail(f"could not read a verdict's issue — {exc}", EXIT_COULD_NOT_READ)
    store.save_pending(document)
    print(render_sweep(result), end="")
    return document.exit_code


def _cmd_record(args, _producer_factory, store: VerdictStore, _issues) -> int:
    try:
        ruling = record(store, args.row, args.verdict, args.ref, datetime.now(UTC))
    except VerdictError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    print(render_record(ruling))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage_health.py",
        description="Sweep GrantSpider's stage-health ledger; record a verdict per RED row.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    swp = sub.add_parser("sweep", help="Run `grantspider dq health --json`; list unruled REDs.")
    swp.add_argument("--days", type=int, default=None, help="Window length (producer default 7).")
    swp.set_defaults(func=_cmd_sweep)
    rec = sub.add_parser("record", help="Record a verdict for one RED row of the last sweep.")
    rec.add_argument("row", help="The row key the sweep printed, e.g. ledger_stale")
    rec.add_argument("verdict", choices=VERDICTS)
    rec.add_argument("--ref", default="", help="GS#<n> for filed/known; free text for fixed.")
    rec.set_defaults(func=_cmd_record)
    return parser


def main(
    argv: list[str],
    *,
    producer_factory: Callable = default_producer,
    store: VerdictStore | None = None,
    issue_states: IssueStates | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    return args.func(
        args,
        producer_factory,
        store if store is not None else default_store(),
        issue_states if issue_states is not None else GithubIssueStates(),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
