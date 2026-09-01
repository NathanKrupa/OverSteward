#!/usr/bin/env python
# ABOUTME: OUTER entrypoint for the Gemini quality-rater pass over live estate pages.
# ABOUTME: Thin: parse args, call the judge service, write both reports, map failures to exit codes.

"""Judge live estate pages the way a search quality rater would.

AG has no search traffic yet, so a real A/B test of the new page designs is
impossible before launch. This is the pre-flight available instead: a rubric
score per page, and pairwise comparisons run in both orders. It is a
*quality-rater pass*, not a ranking predictor — the honest test is still Search
Console after launch.

Pages are fetched through the signed steward probe, so Cloudflare's challenge
is never what gets judged.

Exit codes carry meaning and must not be collapsed:

* **0** — a measured answer; both reports were written.
* **1** — a page or the judge could not be read, or the budget stopped the run.
* **2** — nothing was configured to look: no Gemini key, or no probe token.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from oversteward.judge.config import JudgeConfigError, judge_from_env
from oversteward.judge.ground_truth import resolve_ground_truth
from oversteward.judge.models import JudgeReadError, Manifest, manifest_from_mapping
from oversteward.judge.report import compare_json, compare_markdown, score_json, score_markdown
from oversteward.judge.service import (
    Budget,
    BudgetExceeded,
    CompareReport,
    ScoreReport,
    compare_manifest,
    score_manifest,
)
from oversteward.probe.client import fetch
from oversteward.probe.config import ProbeConfigError, probe_token_from_env

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports" / "judge"

DEFAULT_BUDGET_USD = 1.00

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="page_judge.py",
        description="Gemini quality-rater pass over live estate pages (rubric + pairwise).",
    )
    parser.add_argument("command", choices=("score", "compare"))
    parser.add_argument("manifest", help="YAML manifest of URLs by page type, and pairs.")
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=DEFAULT_BUDGET_USD,
        help=f"Hard cap; the call that would cross it is never issued (default {DEFAULT_BUDGET_USD:.2f}).",
    )
    parser.add_argument("--name", default="", help="Report name; defaults to the manifest's own.")
    return parser


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _judge_manifest(
    command: str,
    judge,
    fetch_page: Callable,
    manifest: Manifest,
    budget: Budget,
    ground_truth: dict,
) -> ScoreReport | CompareReport:
    """Run the command the operator named. Only ``score`` is judged against facts."""
    if command == "score":
        return score_manifest(judge, fetch_page, manifest, budget, ground_truth=ground_truth)
    return compare_manifest(judge, fetch_page, manifest, budget)


def _write(reports_dir: Path, name: str, markdown: str, payload: dict) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(UTC):%Y-%m-%d}-{name}"
    (reports_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
    path = reports_dir / f"{stem}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main(
    argv: list[str],
    *,
    judge_factory: Callable = judge_from_env,
    token_factory: Callable[[], str] = probe_token_from_env,
    fetcher: Callable = fetch,
    reports_dir: Path = REPORTS_DIR,
) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = Path(args.manifest)
    manifest = manifest_from_mapping(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {},
        name=args.name,
    )
    try:
        # Resolved before the judge is even built: a fixture path that does not
        # exist must cost an exit code, never a round of billed calls scored
        # against facts that were never loaded.
        ground_truth = resolve_ground_truth(manifest.ground_truth, manifest_path.resolve().parent)
    except JudgeReadError as exc:
        return _fail(f"could not read — {exc}", EXIT_COULD_NOT_LOOK)

    try:
        judge = judge_factory()
        token = token_factory()
    except (JudgeConfigError, ProbeConfigError) as exc:
        return _fail(f"could not look — {exc}", EXIT_MISCONFIGURED)

    budget = Budget(limit_usd=args.budget_usd)
    try:
        report = _judge_manifest(
            args.command, judge, lambda url: fetcher(url, token), manifest, budget, ground_truth
        )
    except BudgetExceeded as exc:
        return _fail(f"budget stopped the run — {exc}", EXIT_COULD_NOT_LOOK)
    except JudgeReadError as exc:
        return _fail(
            f"could not read — {exc} (spent ${budget.spent_usd:.6f} over {budget.calls} call(s))",
            EXIT_COULD_NOT_LOOK,
        )

    render = score_markdown if args.command == "score" else compare_markdown
    to_json = score_json if args.command == "score" else compare_json
    path = _write(reports_dir, manifest.name, render(report), to_json(report))
    print(f"{path.with_suffix('.md')}\n{path}\nspent ${budget.spent_usd:.4f} over {budget.calls} call(s)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
