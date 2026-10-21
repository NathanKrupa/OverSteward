#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the nightly Estate Brief — reads the estate, writes the vault note.
# ABOUTME: Thin: load registry, call the brief service, write the note, map failures to exit codes.

"""Write the Estate Brief: what shipped, the one ask, and anything URGENT.

The note goes to ``--out`` (or ``$ESTATE_BRIEF_PATH``), which is the vault's
``GTD/Estate Brief.md`` on the nightly timer. The morning check-in reads it
aloud; it cannot run a shell, so this note is its only view of the estate.

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer, including ``0 shipped``.
* **1** — GitHub could not be read (nothing is written), the vault folder is
  missing or unwritable, or the Railway liveness sweep could not look (the
  note is still written, naming the blind source under URGENT).
* **2** — nothing configured: no registry context has a GitHub remote, no
  output path was given, or no context carries a ``railway:`` block (the note
  is still written, saying so under URGENT).
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
from oversteward.board.config import github_repos_from_registry
from oversteward.brief.client import read_activity
from oversteward.brief.compose import (
    ActivityReader,
    Brief,
    UrgentRead,
    UrgentReader,
    compose,
    liveness_urgent,
    render,
)
from oversteward.liveness.config import projects_from_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"
OUT_ENV = "ESTATE_BRIEF_PATH"

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2

_URGENT_EXIT = {
    UrgentRead.MEASURED: EXIT_OK,
    UrgentRead.BLIND: EXIT_COULD_NOT_LOOK,
    UrgentRead.UNCONFIGURED: EXIT_MISCONFIGURED,
}


def load_registry() -> dict:
    """Read the one registry this repo owns — a fixed path, never caller-supplied."""
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
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


def _liveness(loaded: dict) -> UrgentReader:
    return lambda: liveness_urgent(projects_from_registry(loaded))


def _parser(environ: Mapping[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=environ.get(OUT_ENV), help="note path")
    parser.add_argument("--hours", type=int, default=24, help="window length (default 24)")
    return parser


def _publish(brief: Brief, out: Path, repos_read: int) -> int:
    try:
        write_note(out, render(brief))
    except OSError as exc:
        return _fail(f"could not write the note — {exc}", EXIT_COULD_NOT_LOOK)
    print(f"{brief.shipped_count} shipped from {len(brief.shipped)} of {repos_read} repos → {out}")
    code = _URGENT_EXIT[brief.urgent_read]
    if code != EXIT_OK:
        return _fail("URGENT source not measured — " + "; ".join(brief.urgent), code)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    registry: Callable[[], dict] = load_registry,
    urgent: Callable[[dict], UrgentReader] = _liveness,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    read: ActivityReader = read_activity,
    environ: Mapping[str, str] = os.environ,
) -> int:
    args = _parser(environ).parse_args(argv)
    if args.out is None:
        return _fail(f"no output path — pass --out or set {OUT_ENV}", EXIT_MISCONFIGURED)
    loaded = registry()
    repos = github_repos_from_registry(loaded)
    if not repos:
        return _fail("no registry.yaml context has a GitHub remote", EXIT_MISCONFIGURED)
    window = timedelta(hours=args.hours)
    try:
        brief = compose(repos, now=now(), window=window, read_urgent=urgent(loaded), read=read)
    except GhError as exc:
        return _fail(f"could not read GitHub — {exc}", EXIT_COULD_NOT_LOOK)
    return _publish(brief, Path(args.out), len(repos))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
