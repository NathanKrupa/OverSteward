#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for issue intake (OS#613) — tribe-first queue, displaced notice, backfill, labels.
# ABOUTME: Thin: parse args, read GitHub through the connector, call the intake services, print.

"""Issue intake: the tribe / agent-finding split.

Verbs:

* ``queue <repo>`` — the repository's ready-for-agent issues, ``tribe`` first.
* ``displaced <repo> <n>`` — the ready ``tribe`` issues a dispatch of ``#n``
  passes over. A notice, never a refusal: it exits 0 either way.
* ``backfill [--apply]`` — classify every open issue in every covered
  repository and write the report. Dry run unless ``--apply`` is given.
* ``labels`` — upsert the dispatch label taxonomy on every covered repository.

Covered repositories are every ``dispatch_target`` in ``registry.yaml`` plus
OverSteward. Exit codes must not be collapsed: **0** a measured answer, **1**
GitHub could not be read or written (or the issue named is not open), **2**
nothing to look at — an unknown repository or no covered repositories.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.board.config import RepoRef
from oversteward.intake import github
from oversteward.intake.backfill import apply_plan, classify_all, plan, render_report
from oversteward.intake.labels import DISPATCH_LABELS, LabelSpec, ensure_labels
from oversteward.intake.queue import (
    dispatch_queue,
    displaced_by,
    render_displacement,
    render_queue,
)
from oversteward.intake.service import read_repo, read_repos, repos_for

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "registry.yaml"

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_NOTHING_TO_LOOK_AT = 2


@dataclass(frozen=True)
class Deps:
    repos: list[RepoRef]
    list_issues: Callable[[str], list[dict]]
    add_labels: Callable[[str, int, tuple[str, ...]], object]
    upsert_label: Callable[[str, LabelSpec], object]


def registry_repos() -> list[RepoRef]:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return repos_for(yaml.safe_load(handle) or {})


def _live_deps() -> Deps:
    return Deps(
        repos=registry_repos(),
        list_issues=github.list_open_issues,
        add_labels=github.add_labels,
        upsert_label=github.upsert_label,
    )


def _find(deps: Deps, repo_id: str) -> RepoRef | None:
    repo = next((r for r in deps.repos if r.id == repo_id), None)
    if repo is None:
        known = ", ".join(r.id for r in deps.repos)
        print(f"ERROR: unknown repo {repo_id!r} (known: {known})", file=sys.stderr)
    return repo


def _cmd_queue(args: argparse.Namespace, deps: Deps) -> int:
    repo = _find(deps, args.repo)
    if repo is None:
        return EXIT_NOTHING_TO_LOOK_AT
    print(render_queue(repo.id, dispatch_queue(read_repo(repo, deps.list_issues))), end="")
    return EXIT_OK


def _cmd_displaced(args: argparse.Namespace, deps: Deps) -> int:
    repo = _find(deps, args.repo)
    if repo is None:
        return EXIT_NOTHING_TO_LOOK_AT
    issues = read_repo(repo, deps.list_issues)
    target = next((i for i in issues if i.number == args.number), None)
    if target is None:
        print(f"ERROR: {repo.id}#{args.number} is not an open issue", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(render_displacement(repo.id, target, displaced_by(target, issues)), end="")
    return EXIT_OK


def _cmd_backfill(args: argparse.Namespace, deps: Deps) -> int:
    rows = classify_all(read_repos(deps.repos, deps.list_issues))
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    report = render_report(rows, per_class=args.sample, seed=args.seed, generated=generated)
    args.out.write_text(report, encoding="utf-8")
    steps = plan(rows)
    print(f"{len(rows)} open issues classified; {len(steps)} would gain labels. Report: {args.out}")
    if not args.apply:
        print("Dry run — nothing applied. Re-run with --apply after Nathan has read the sample.")
        return EXIT_OK
    by_id = {r.id: r.full_name for r in deps.repos}
    failures = apply_plan(
        steps, lambda repo, number, labels: deps.add_labels(by_id[repo], number, labels)
    )
    for failure in failures:
        print(f"FAILED {failure.step.repo}#{failure.step.number}: {failure.error}", file=sys.stderr)
    print(f"Applied {len(steps) - len(failures)} of {len(steps)} label additions.")
    return EXIT_COULD_NOT_LOOK if failures else EXIT_OK


def _cmd_labels(args: argparse.Namespace, deps: Deps) -> int:
    names = [r.full_name for r in deps.repos]
    failures = ensure_labels(names, deps.upsert_label)
    for repo, label, error in failures:
        print(f"FAILED {repo} {label}: {error}", file=sys.stderr)
    failed = {repo for repo, _label, _error in failures}
    for repo in names:
        state = "FAILED (see stderr)" if repo in failed else "ok"
        print(f"{repo}: {len(DISPATCH_LABELS)} dispatch labels upserted — {state}")
    return EXIT_COULD_NOT_LOOK if failures else EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    queue = verbs.add_parser("queue", help="ready-for-agent issues, tribe first")
    queue.add_argument("repo")
    queue.set_defaults(handler=_cmd_queue)
    displaced = verbs.add_parser("displaced", help="ready tribe issues a dispatch passes over")
    displaced.add_argument("repo")
    displaced.add_argument("number", type=int)
    displaced.set_defaults(handler=_cmd_displaced)
    backfill = verbs.add_parser("backfill", help="classify every open issue (dry run by default)")
    backfill.set_defaults(handler=_cmd_backfill)
    backfill.add_argument("--out", type=Path, required=True, help="where to write the report")
    backfill.add_argument("--sample", type=int, default=10, help="sample rows per class")
    backfill.add_argument("--seed", type=int, default=0, help="sample seed")
    backfill.add_argument("--apply", action="store_true", help="add the proposed labels")
    labels = verbs.add_parser("labels", help="upsert the dispatch label taxonomy on every repo")
    labels.set_defaults(handler=_cmd_labels)
    return parser


def main(argv: list[str] | None = None, *, deps: Deps | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        deps = deps or _live_deps()
    except ValueError as exc:
        print(f"ERROR: registry.yaml — {exc}", file=sys.stderr)
        return EXIT_NOTHING_TO_LOOK_AT
    if not deps.repos:
        print("ERROR: no repositories to cover in registry.yaml", file=sys.stderr)
        return EXIT_NOTHING_TO_LOOK_AT
    try:
        return args.handler(args, deps)
    except github.GhError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK


if __name__ == "__main__":
    sys.exit(main())
