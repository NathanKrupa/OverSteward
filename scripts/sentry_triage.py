# ABOUTME: OUTER entrypoint for /sentry-triage — sweeps unresolved Sentry issues and records verdicts.
# ABOUTME: Thin: parse args, call the triage service, print, map failures to distinct exit codes.

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oversteward.sentry.client import (
    SentryConfigError,
    SentryUnavailableError,
    client_from_env,
)
from oversteward.sentry.render import render_record, render_sweep
from oversteward.sentry.triage import VERDICTS, TriageError, TriageStore, record, sweep

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "data" / "sentry" / "ledger.jsonl"
PENDING_PATH = REPO_ROOT / "data" / "sentry" / "pending.json"

#: Exit codes carry meaning and must not be collapsed: 0 is a measured answer
#: (a queue, or an honest "nothing to triage"); 1 means Sentry could not be
#: read; 2 means we were not configured to look, or were asked the impossible.
EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def default_store() -> TriageStore:
    return TriageStore(ledger_path=LEDGER_PATH, pending_path=PENDING_PATH)


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _cmd_sweep(_args: argparse.Namespace, client_factory: Callable, store: TriageStore) -> int:
    try:
        client = client_factory()
    except SentryConfigError as exc:
        return _fail(f"could not look — {exc}", EXIT_MISCONFIGURED)

    try:
        result = sweep(client, store)
    except SentryUnavailableError as exc:
        return _fail(f"could not look — {exc}", EXIT_COULD_NOT_LOOK)

    store.save_pending(result.new_issues)
    print(render_sweep(result), end="")
    return EXIT_OK


def _cmd_record(args: argparse.Namespace, client_factory: Callable, store: TriageStore) -> int:
    if args.resolve:
        code = _resolve_in_sentry(args, client_factory, store)
        if code != EXIT_OK:
            return code
    try:
        entry = record(store, args.short_id, args.verdict, args.ref, datetime.now(UTC))
    except TriageError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    print(render_record(entry))
    return EXIT_OK


def _resolve_in_sentry(
    args: argparse.Namespace,
    client_factory: Callable,
    store: TriageStore,
) -> int:
    """Mark the issue resolved in Sentry before the ledger line is written.

    Order matters: the network step runs first, so a Sentry failure can never
    leave a ledger claiming a resolution that never happened.
    """
    issue = store.pending().get(args.short_id)
    if issue is None:
        return _fail(f"{args.short_id} is not in the last sweep's queue.", EXIT_MISCONFIGURED)
    try:
        client_factory().resolve_issue(issue.id, comment=args.ref)
    except SentryConfigError as exc:
        return _fail(f"could not resolve — {exc}", EXIT_MISCONFIGURED)
    except SentryUnavailableError as exc:
        return _fail(f"could not resolve {args.short_id} — {exc}", EXIT_COULD_NOT_LOOK)
    return EXIT_OK


def _add_record_command(sub) -> None:
    rec = sub.add_parser("record", help="Record a verdict for one swept issue.")
    rec.add_argument("short_id", metavar="SHORT_ID", help="e.g. AIGRANTHELPER-4F")
    rec.add_argument("verdict", choices=VERDICTS)
    rec.add_argument("--ref", default="", help="Where the verdict landed: GS#2166, or a reason.")
    rec.add_argument(
        "--resolve",
        action="store_true",
        help="Also mark it resolved in Sentry — never ignored, so a regression reopens loudly.",
    )
    rec.set_defaults(func=_cmd_record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentry_triage.py",
        description="Deterministic Sentry triage: sweep the unread queue, record verdicts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "sweep", help="Unresolved Sentry issues with no recorded verdict."
    ).set_defaults(func=_cmd_sweep)
    _add_record_command(sub)
    return parser


def main(
    argv: list[str],
    *,
    client_factory: Callable = client_from_env,
    store: TriageStore | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, client_factory, store if store is not None else default_store())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
