#!/usr/bin/env python3
# ABOUTME: OUTER entrypoint — alert the operator when a dispatched agent's work stops moving.
# ABOUTME: Thin: parse args, find the checkout in registry.yaml, call oversteward.dispatch_watchdog.
"""Dispatch watchdog: the silent-loop guard (AG#947, OS#632).

Watches the dispatch worktree's commits, ``.review*`` files and ``.verify-marker``,
and the remote ``*issue-<n>*`` branch. The signals are in
``oversteward.dispatch_watchdog``.

* **0** — the run finished: the dispatch worktree, once seen, was torn down.
* **3** — alert: nothing moved for ``--warn-min`` minutes.
* **2** — could not look: no registry context with a ``local_path`` for the repo
  and no ``--checkout``.
"""

from __future__ import annotations

import argparse
import sys
import time
from functools import partial
from pathlib import Path

import yaml

from oversteward import dispatch_watchdog as wd

REGISTRY = Path(__file__).resolve().parents[2] / "registry.yaml"


def _alert_text(full_name: str, issue: int, reason: str) -> str:
    return (
        f"⏱ Dispatch watchdog: {full_name}#{issue} — {reason}. "
        "Check the agent transcript's turn count; TaskStop and re-dispatch if it is looping."
    )


def _checkout(full_name: str, given: Path | None) -> Path | None:
    if given is not None:
        return given
    with REGISTRY.open(encoding="utf-8") as f:
        contexts = (yaml.safe_load(f) or {}).get("contexts") or []
    return wd.checkout_for(full_name, contexts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch watchdog — alert when a dispatched agent's work stops moving."
    )
    parser.add_argument("full_name", help="owner/repo, e.g. NathanKrupa/aigranthelper")
    parser.add_argument("issue", type=int, help="issue number being dispatched")
    parser.add_argument("--warn-min", type=float, default=wd.DEFAULT_WARN_MIN,
                        help="minutes with nothing moving before the alert")
    parser.add_argument("--poll-sec", type=float, default=wd.DEFAULT_POLL_SEC,
                        help="seconds between readings")
    parser.add_argument("--checkout", type=Path, default=None,
                        help="the repo's primary checkout (default: its registry local_path)")
    args = parser.parse_args(argv)

    checkout = _checkout(args.full_name, args.checkout)
    if checkout is None:
        print(f"could not look: no registry local_path for {args.full_name}; pass --checkout",
              file=sys.stderr)
        return wd.EXIT_UNLOCATED
    worktree = wd.worktree_path(checkout, args.issue)
    print(f"watching {worktree} and {args.full_name} *issue-{args.issue}* "
          f"(warn at {args.warn_min:.0f}m quiet)", flush=True)
    read = partial(wd.read_snapshot, worktree,
                   partial(wd.remote_branches, args.full_name, args.issue))
    verdict = wd.watch(
        read, warn_min=args.warn_min, poll_sec=args.poll_sec,
        sleeper=time.sleep, clock=time.monotonic,
        report=lambda v, m: print(f"~{m:.0f}m progressing: {v.reason}", flush=True),
    )
    if verdict.should_alert:
        print(_alert_text(args.full_name, args.issue, verdict.reason))
    else:
        print(f"{verdict.status}: {verdict.reason}")
    return wd.exit_code(verdict)


if __name__ == "__main__":
    sys.exit(main())
