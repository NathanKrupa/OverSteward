#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the nightly Estate Brief — reads the estate, writes the vault note.
# ABOUTME: Thin: load registry, call the brief service, write the note, map failures to exit codes.

"""Write the Estate Brief: what shipped, the one ask, anything URGENT, and what was shelved.

The note goes to ``--out`` (or ``$ESTATE_BRIEF_PATH``), which is the vault's
``GTD/Estate Brief.md`` on the nightly timer. The morning check-in reads it
aloud; it cannot run a shell, so this note is its only view of the estate.
"Shelved overnight" reads the abandoned-work sweep's ledger at
``--shelve-ledger`` (or ``$SHELVE_LEDGER_PATH``), which must lie inside
``~/.local/state/oversteward/``; ``--sweep-max-age-minutes`` makes a sweep run
older than that count as no run (the nightly unit passes it, since its sweep
runs moments before the brief). URGENT marks failures already filed through
``data/known_failures.yaml``.

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, including ``0 shipped``.
* **1** — GitHub could not be read (nothing is written), the vault folder is
  missing or unwritable, the Railway liveness sweep could not look, or the
  sweep ledger is unreadable or holds no completed (and, when asked, fresh)
  run in the window (in those three the note is still written, naming the gap).
* **2** — nothing configured: no registry context has a GitHub remote, no
  output path was given, no context carries a ``railway:`` block, no sweep
  ledger was given, the ledger path lies outside the state directory, or
  ``data/known_failures.yaml`` holds an entry that is not an exact key and
  issue (in the middle two the note is still written, saying so).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from oversteward.board.client import GhError
from oversteward.board.config import RepoRef, github_repos_from_registry
from oversteward.brief.client import issue_is_open, read_activity, read_thread
from oversteward.brief.compose import (
    ActivityReader,
    Brief,
    KnownIssue,
    ShelvedRead,
    ShelvedReader,
    ThreadReader,
    UrgentRead,
    UrgentReader,
    compose,
    known_failures,
    liveness_urgent,
    render,
)
from oversteward.liveness.config import projects_from_registry
from oversteward.shelve import ledger

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
KNOWN_PATH = REPO_ROOT / "data" / "known_failures.yaml"
OUT_ENV = "ESTATE_BRIEF_PATH"

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2

_URGENT_EXIT = {
    UrgentRead.MEASURED: EXIT_OK,
    UrgentRead.BLIND: EXIT_COULD_NOT_LOOK,
    UrgentRead.UNCONFIGURED: EXIT_MISCONFIGURED,
}
_SHELVED_EXIT = {
    ShelvedRead.MEASURED: EXIT_OK,
    ShelvedRead.NO_RUN: EXIT_COULD_NOT_LOOK,
    ShelvedRead.UNREADABLE: EXIT_COULD_NOT_LOOK,
    ShelvedRead.UNCONFIGURED: EXIT_MISCONFIGURED,
}


def load_registry() -> dict:
    """Read the one registry this repo owns — a fixed path, never caller-supplied."""
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_known() -> dict:
    """Read the recorded known-failure map — a fixed path in this repo, never caller-supplied."""
    with open(KNOWN_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def write_note(path: Path, text: str) -> None:
    """Replace the note atomically; never create the folder it lives in.

    A missing folder most likely means the Windows drive is not mounted;
    creating it would plant a stray tree on the Linux side that nothing reads.
    """
    if not path.parent.is_dir():
        raise FileNotFoundError(f"vault folder {path.parent} does not exist")
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(text, encoding="utf-8")
    os.replace(staging, path)


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _liveness(loaded: dict, known: Mapping[str, KnownIssue], repos: list[RepoRef]) -> UrgentReader:
    by_id = {repo.id: repo for repo in repos}
    return lambda: liveness_urgent(
        projects_from_registry(loaded),
        known=known,
        is_open=lambda issue: issue_is_open(by_id[issue.repo], issue.number),
    )


def _minutes(value: int | None) -> timedelta | None:
    return None if value is None else timedelta(minutes=value)


def _ledger_reader(path: Path | None, state_dir: Path) -> ShelvedReader | None:
    """Read the sweep ledger; ``ValueError`` here (before any read) when the path is outside."""
    if path is None:
        return None
    safe = ledger.confine(path, state_dir)

    def read() -> tuple[ledger.LedgerEntry, ...]:
        with open(safe, encoding="utf-8") as handle:
            return ledger.parse(handle.read())

    return read


def _parser(environ: Mapping[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=environ.get(OUT_ENV), help="note path")
    parser.add_argument("--hours", type=int, default=24, help="window length (default 24)")
    parser.add_argument("--shelve-ledger", type=Path, default=environ.get(ledger.LEDGER_ENV),
                        help=f"abandoned-work sweep ledger (default ${ledger.LEDGER_ENV})")
    parser.add_argument("--sweep-max-age-minutes", type=int, default=None,
                        help="treat a sweep run older than this as no run")
    return parser


def _publish(brief: Brief, out: Path, repos_read: int) -> int:
    try:
        write_note(out, render(brief))
    except OSError as exc:
        return _fail(f"could not write the note — {exc}", EXIT_COULD_NOT_LOOK)
    print(f"{brief.shipped_count} shipped from {len(brief.shipped)} of {repos_read} repos → {out}")
    codes = []
    if _URGENT_EXIT[brief.urgent_read] != EXIT_OK:
        codes.append(_fail("URGENT source not measured — " + "; ".join(brief.urgent),
                           _URGENT_EXIT[brief.urgent_read]))
    if _SHELVED_EXIT[brief.shelved.read] != EXIT_OK:
        codes.append(_fail(f"sweep ledger not measured — {brief.shelved.read.value} "
                           f"{brief.shelved.detail}".rstrip(), _SHELVED_EXIT[brief.shelved.read]))
    # "Could not look" outranks "not configured": it is the one that hides a failure.
    return min(codes) if codes else EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    registry: Callable[[], dict] = load_registry,
    known: Callable[[], dict] = load_known,
    urgent: Callable[[dict, Mapping[str, KnownIssue], list[RepoRef]], UrgentReader] = _liveness,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    read: ActivityReader = read_activity,
    thread: ThreadReader = read_thread,
    environ: Mapping[str, str] = os.environ,
    state_dir: Path = ledger.STATE_DIR,
) -> int:
    args = _parser(environ).parse_args(argv)
    if args.out is None:
        return _fail(f"no output path — pass --out or set {OUT_ENV}", EXIT_MISCONFIGURED)
    loaded = registry()
    repos = github_repos_from_registry(loaded)
    if not repos:
        return _fail("no registry.yaml context has a GitHub remote", EXIT_MISCONFIGURED)
    try:
        known_map = known_failures(known(), repos)
        read_shelved = _ledger_reader(args.shelve_ledger, state_dir)
    except ValueError as exc:
        return _fail(str(exc), EXIT_MISCONFIGURED)
    window = timedelta(hours=args.hours)
    try:
        brief = compose(repos, now=now(), window=window,
                        read_urgent=urgent(loaded, known_map, repos), read=read,
                        read_thread=thread, read_shelved=read_shelved,
                        sweep_max_age=_minutes(args.sweep_max_age_minutes))
    except GhError as exc:
        return _fail(f"could not read GitHub — {exc}", EXIT_COULD_NOT_LOOK)
    return _publish(brief, Path(args.out), len(repos))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
