#!/usr/bin/env python
# ABOUTME: Validates the reviewer eval fixtures (CI) or grades captured reviewer verdicts (manual).
# ABOUTME: Thin shell over oversteward.reviewer_eval — parse argv, print, pick an exit code.

"""Run the adversarial reviewer's eval set (OS#428 §6).

    scripts/review/run_reviewer_eval.py --validate           # deterministic, CI
    scripts/review/run_reviewer_eval.py --grade <results>    # needs an LLM run

`--validate` proves the eval set is **well-formed**. It does not run a reviewer
and measures no recall; a green validate is not a green eval, and the output
says so on every run so a passing CI line cannot be misread later.

`--grade` reads one `<case>.md` per case from a results directory, each holding
that case's reviewer output, and reports which known-bad diffs were caught.
That is the measurement OS#428's acceptance asks for.

Exit codes: 0 measured-and-good, 1 problems found, 2 could not look.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve the package from THIS checkout's src/ — see scripts/lint/trajectory_tags.py.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.reviewer_eval import (  # noqa: E402
    EXIT_COULD_NOT_LOOK,
    EXIT_OK,
    EXIT_VIOLATIONS,
    EvalSetError,
    grade,
    load_cases,
    validate,
)

GATE = "reviewer-eval:"
DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[2] / "tests" / "reviewer_eval"

VALIDATE_CAVEAT = (
    "This checked the fixtures and the schema only. It ran no reviewer and "
    "measured no recall — use --grade for that."
)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_reviewer_eval.py")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="check the fixtures are well-formed")
    mode.add_argument("--grade", metavar="RESULTS_DIR", help="grade captured reviewer verdicts")
    parser.add_argument("--eval-dir", default=str(DEFAULT_EVAL_DIR))
    return parser.parse_args(argv)


def _do_validate(cases: list) -> int:
    problems = validate(cases)
    if problems:
        for problem in problems:
            sys.stderr.write(f"{GATE} {problem}\n")
        sys.stderr.write(f"{GATE} FAILED — {len(problems)} problem(s) in the eval set.\n")
        return EXIT_VIOLATIONS
    # Always name the count: "all 6 cases well-formed" is a measurement,
    # "ok" is a claim.
    sys.stdout.write(f"{GATE} {len(cases)} cases well-formed.\n")
    sys.stdout.write(f"{GATE} {VALIDATE_CAVEAT}\n")
    return EXIT_OK


def _do_grade(cases: list, results_dir: Path) -> int:
    if not results_dir.is_dir():
        sys.stderr.write(f"{GATE} COULD NOT LOOK — no results directory at {results_dir}\n")
        return EXIT_COULD_NOT_LOOK
    results = {}
    for case in cases:
        path = results_dir / f"{case.name}.md"
        results[case.name] = path.read_text(encoding="utf-8") if path.is_file() else None

    graded = grade(cases, results)
    for row in graded:
        mark = "PASS" if row.caught else "MISS"
        sys.stdout.write(
            f"{GATE} [{mark}] {row.name}: expected {row.expected}, "
            f"got {row.actual or '-'} — {row.note}\n"
        )
    missed = [row for row in graded if not row.caught]
    sys.stdout.write(f"{GATE} {len(graded) - len(missed)}/{len(graded)} cases correct.\n")
    if missed:
        sys.stderr.write(
            f"{GATE} FAILED — {len(missed)} case(s) missed. The reviewer does not yet "
            "catch what it was built to catch; do not gate PRs on it.\n"
        )
        return EXIT_VIOLATIONS
    return EXIT_OK


def main(argv: list[str]) -> int:
    args = _parse(argv)
    try:
        cases = load_cases(Path(args.eval_dir))
    except EvalSetError as exc:
        sys.stderr.write(f"{GATE} COULD NOT LOOK — {exc}\n")
        return EXIT_COULD_NOT_LOOK

    if args.validate:
        return _do_validate(cases)
    return _do_grade(cases, Path(args.grade))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
