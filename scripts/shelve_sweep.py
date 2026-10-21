#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the abandoned-work sweep — dry-run by default, --apply to write to GitHub.
# ABOUTME: Thin: load registry, read through the shelve service, ledger every action, map failures to exits.

"""Shelve idle pull requests and agent findings; report stale branches and worktrees.

Dry-run is the default and writes nothing to GitHub. ``--apply`` performs the
writes. Either way every decided action is appended to the JSONL ledger at
``--ledger`` (or ``$SHELVE_LEDGER_PATH``) with ``mode`` ``dry`` or ``applied``.
The rules are in ``oversteward.shelve.sweep``.

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, including no actions.
* **1** — GitHub or git could not be read, the ledger could not be written,
  or GitHub refused one or more writes (each is named; the other actions still
  ran, and the ledger holds every one that completed).
* **2** — nothing configured: no ledger path, a ledger path outside
  ``~/.local/state/oversteward/``, no dispatch target in the registry, or
  ``--apply`` against a repository without the ``shelved`` label.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

import yaml

from oversteward.board.client import GhError
from oversteward.shelve import ledger
from oversteward.shelve.client import GhWriter, read_linked_issue, read_snapshot
from oversteward.shelve.sweep import (
    MissingLabelError,
    SweepTarget,
    Writer,
    execute,
    plan,
    render,
    survey,
    targets_from_registry,
)
from oversteward.shelve.worktrees import Worktree, WorktreeReadError, read_worktrees

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
DOCTOR_PATH = REPO_ROOT / "scripts" / "dev" / "worktree_doctor.py"
LEDGER_ENV = ledger.LEDGER_ENV
STATE_DIR = ledger.STATE_DIR

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2

TreeReader = Callable[[SweepTarget], tuple[Worktree, ...]]


def load_registry() -> dict:
    """Read the one registry this repo owns — a fixed path, never caller-supplied."""
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def append_ledger(path: Path, base: Path, entries: Sequence[ledger.LedgerEntry]) -> None:
    """Append ``entries`` to the ledger inside ``base``, creating its folder if needed."""
    if not entries:
        return
    safe = ledger.confine(path, base)
    safe.parent.mkdir(parents=True, exist_ok=True)
    with open(safe, "a", encoding="utf-8") as handle:
        handle.write(ledger.to_lines(entries))


def doctor_trees() -> TreeReader:
    """Read worktrees through the doctor's own ``git worktree list`` parser."""
    spec = importlib.util.spec_from_file_location("worktree_doctor", DOCTOR_PATH)
    doctor = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while the class is built.
    sys.modules.setdefault(spec.name, doctor)
    spec.loader.exec_module(doctor)

    def checkouts(primary: Path) -> list[tuple[Path, str | None]]:
        try:
            return doctor.worktree_checkouts(primary)
        except doctor.CouldNotLook as exc:
            raise WorktreeReadError(str(exc)) from exc

    def read(target: SweepTarget) -> tuple[Worktree, ...]:
        if target.local_path is None:
            return ()
        return read_worktrees(target.repo.id, target.local_path, target.trunk, checkouts=checkouts)

    return read


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _parser(environ: Mapping[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, default=environ.get(LEDGER_ENV),
                        help=f"JSONL action ledger (default ${LEDGER_ENV})")
    parser.add_argument("--apply", action="store_true",
                        help="perform the writes; without it nothing is written to GitHub")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    registry: Callable[[], dict] = load_registry,
    trees: Callable[[], TreeReader] = doctor_trees,
    writer: Callable[[], Writer] = GhWriter,
    read_repo=read_snapshot,
    read_issue=read_linked_issue,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    environ: Mapping[str, str] = os.environ,
    state_dir: Path = STATE_DIR,
) -> int:
    args = _parser(environ).parse_args(argv)
    if args.ledger is None:
        return _fail(f"no ledger path — pass --ledger or set {LEDGER_ENV}", EXIT_MISCONFIGURED)
    try:
        ledger_file = ledger.confine(args.ledger, state_dir)
    except ValueError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    targets = targets_from_registry(registry())
    if not targets:
        return _fail("no registry.yaml context is a dispatch target", EXIT_MISCONFIGURED)
    moment = now()
    try:
        found = survey(targets, now=moment, read_repo=read_repo, read_issue=read_issue,
                       read_trees=trees())
        decided = plan(targets, found, moment)
        outcome = execute(decided, apply=args.apply, writer=writer() if args.apply else None,
                          record=lambda rows: append_ledger(ledger_file, state_dir, rows), now=moment)
    except MissingLabelError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    except (GhError, WorktreeReadError, OSError) as exc:
        return _fail(f"could not finish the sweep — {exc}", EXIT_COULD_NOT_LOOK)
    print(render(outcome.entries, apply=args.apply, unlabelled=decided.unlabelled), end="")
    for failure in outcome.failures:
        action = failure.action
        print(f"ERROR: GitHub refused to {action.verb} {action.repo.id}#{action.number} — "
              f"{failure.error}", file=sys.stderr)
    return EXIT_COULD_NOT_LOOK if outcome.failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
