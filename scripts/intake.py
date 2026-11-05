#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for issue intake (OS#613) — queue, line, displaced notice, backfill, labels.
# ABOUTME: Thin: parse args, read GitHub through the connector, call the intake services, print.

"""Issue intake: the tribe / agent-finding split.

Verbs:

* ``queue <repo>`` — the repository's ready-for-agent issues, ``ci-red`` then
  ``tribe`` first, under a ``LINE STOPPED`` header while a ``ci-red`` issue is open.
* ``line <repo> <n> [--override '<reason>']`` — whether the line lets ``#n``
  dispatch (OS#657). Its own exit codes, all but 0 a refusal: **0** allowed,
  **1** GitHub could not be read (or ``#n`` is not open), **2** stopped, an
  unknown repository, or a refused override. ``--override`` lifts a ci-red stop
  (never ``dispatch-paused``) only after a ``LINE OVERRIDE:`` comment has landed
  on every open ci-red issue; one failed comment, or a blank reason, refuses.
* ``displaced <repo> <n>`` — the ready ``tribe`` issues a dispatch of ``#n``
  passes over. A notice, never a refusal: it exits 0 either way.
* ``backfill [--only <label>]... [--apply]`` — classify every open issue in
  every covered repository and write the report. Dry run unless ``--apply`` is
  given; ``--only`` restricts the labels the plan adds.
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
from oversteward.intake.backfill import LABELS, apply_plan, classify_all, plan, render_report
from oversteward.intake.labels import DISPATCH_LABELS, LabelSpec, ensure_labels
from oversteward.intake.line import Allowed, stop_line
from oversteward.intake.queue import (
    dispatch_queue,
    displaced_by,
    is_ci_red,
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
    issue_comments: Callable[[str, int], list[str]]
    comment_issue: Callable[[str, int, str], object]


def registry_repos() -> list[RepoRef]:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return repos_for(yaml.safe_load(handle) or {})


def _live_deps() -> Deps:
    return Deps(
        repos=registry_repos(),
        list_issues=github.list_open_issues,
        add_labels=github.add_labels,
        upsert_label=github.upsert_label,
        issue_comments=github.issue_comments,
        comment_issue=github.comment_issue,
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
    issues = read_repo(repo, deps.list_issues)
    red = [i for i in issues if is_ci_red(i)]
    print(render_queue(repo.id, dispatch_queue(issues), ci_red=red), end="")
    return EXIT_OK


def _override(
    repo: RepoRef, target: int, reason: str, deps: Deps, red_numbers: tuple[int, ...]
) -> int:
    """Record ``LINE OVERRIDE:`` on every open ci-red issue; any failed write refuses."""
    body = f"LINE OVERRIDE: dispatching {repo.id}#{target} \u2014 {reason.strip()}"
    for number in red_numbers:
        try:
            deps.comment_issue(repo.full_name, number, body)
        except github.GhError as exc:
            print(f"OVERRIDE REFUSED: the record on {repo.id}#{number} failed: {exc}")
            return EXIT_NOTHING_TO_LOOK_AT
        print(f"recorded on {repo.id}#{number}: {body}")
    print(f"allowed by override: {repo.id}#{target}")
    return EXIT_OK


def _cmd_line(args: argparse.Namespace, deps: Deps) -> int:
    if args.override is not None and not args.override.strip():
        print("OVERRIDE REFUSED: --override needs a reason", file=sys.stderr)
        return EXIT_NOTHING_TO_LOOK_AT
    repo = _find(deps, args.repo)
    if repo is None:
        return EXIT_NOTHING_TO_LOOK_AT
    issues = read_repo(repo, deps.list_issues)
    target = next((i for i in issues if i.number == args.number), None)
    if target is None:
        print(f"ERROR: {repo.id}#{args.number} is not an open issue", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    verdict = stop_line(target, issues, deps.issue_comments(repo.full_name, target.number))
    if isinstance(verdict, Allowed):
        print(f"line allowed: {verdict.reason}")
        return EXIT_OK
    for reason in verdict.reasons:
        print(f"Line stopped: {reason}")
    if args.override is None:
        return EXIT_NOTHING_TO_LOOK_AT
    if not verdict.overridable:
        print("OVERRIDE REFUSED: dispatch-paused is lifted only by removing its label")
        return EXIT_NOTHING_TO_LOOK_AT
    return _override(repo, target.number, args.override, deps, verdict.ci_red)


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
    only = frozenset(args.only) if args.only else None
    report = render_report(
        rows, per_class=args.sample, seed=args.seed, generated=generated, only=only
    )
    args.out.write_text(report, encoding="utf-8")
    steps = plan(rows, only=only)
    print(f"{len(rows)} open issues classified; {len(steps)} would gain labels. Report: {args.out}")
    if not args.apply:
        flags = "".join(f" --only {label}" for label in sorted(only or ()))
        print(
            f"Dry run — nothing applied. Re-run with{flags} --apply "
            "after Nathan has read the sample."
        )
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
    line = verbs.add_parser("line", help="whether an open ci-red issue stops a dispatch")
    line.add_argument("repo")
    line.add_argument("number", type=int)
    line.add_argument("--override", help="dispatch past ci-red anyway, recorded on each issue")
    line.set_defaults(handler=_cmd_line)
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
    backfill.add_argument(
        "--only",
        action="append",
        choices=LABELS,
        help="add only this label (repeatable); without it, every proposed label",
    )
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
