#!/usr/bin/env python3
# ABOUTME: OUTER entrypoint for /ag-triage — sweeps aigranthelper's ops queues and records verdicts.
# ABOUTME: Thin: parse args, call the triage service, print, map failures to distinct exit codes.

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from oversteward.ag_ops.client import (
    AgOpsConfigError,
    AgOpsUnavailableError,
    client_from_env,
)
from oversteward.ag_ops.render import render_record, render_sweep
from oversteward.ag_ops.triage import (
    ContractDriftError,
    VerdictError,
    parse_verdict,
    record,
    sweep,
)

#: Exit codes carry meaning and must not be collapsed: 0 is a measured answer
#: (a queue, or a clean sweep that names every scanned count); 1 means the seam
#: could not be read — an outage, a timeout, or a producer whose contract
#: drifted out from under us; 2 means we were not configured to look, or asked
#: for a verdict this token may not set.
EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _cmd_sweep(_args: argparse.Namespace, client_factory: Callable) -> int:
    try:
        result = sweep(client_factory())
    except AgOpsConfigError as exc:
        return _fail(f"could not look — {exc}", EXIT_MISCONFIGURED)
    except ContractDriftError as exc:
        return _fail(f"contract drift — {exc}", EXIT_COULD_NOT_LOOK)
    except AgOpsUnavailableError as exc:
        return _fail(f"could not look — {exc}", EXIT_COULD_NOT_LOOK)
    print(render_sweep(result), end="")
    return EXIT_OK


def _cmd_record(args: argparse.Namespace, client_factory: Callable) -> int:
    try:
        requests = [parse_verdict(spec) for spec in args.verdict]
        result = record(client_factory(), requests)
    except VerdictError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    except AgOpsConfigError as exc:
        return _fail(f"could not record — {exc}", EXIT_MISCONFIGURED)
    except ContractDriftError as exc:
        return _fail(f"contract drift — {exc}", EXIT_COULD_NOT_LOOK)
    except AgOpsUnavailableError as exc:
        return _fail(f"could not record — {exc}", EXIT_COULD_NOT_LOOK)
    print(render_record(result), end="")
    return EXIT_OK if result.all_ok else EXIT_MISCONFIGURED


def _add_record_command(sub) -> None:
    rec = sub.add_parser("record", help="Record a batch of verdicts. Idempotent — safe to retry.")
    rec.add_argument(
        "--verdict",
        action="append",
        required=True,
        metavar="KIND:ID:STATUS",
        help="e.g. feedback:<uuid>:responded, correction:<uuid>:rejected. Repeatable.",
    )
    rec.set_defaults(func=_cmd_record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ag_ops_triage.py",
        description="AG operator seam: sweep the ops queues, record verdicts on what is waiting.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "sweep",
        help="Every named ops report, with the counts each one scanned.",
    ).set_defaults(func=_cmd_sweep)
    _add_record_command(sub)
    return parser


def main(argv: list[str], *, client_factory: Callable = client_from_env) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, client_factory)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
