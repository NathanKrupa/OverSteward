# ABOUTME: Validates the adversarial reviewer's eval fixtures and grades a reviewer's verdicts.
# ABOUTME: Validation checks the eval is well-formed; only grading measures whether it catches.

"""The adversarial reviewer's eval set (OS#428 §6).

Two operations, deliberately kept apart because conflating them would be the
false green this whole instrument exists to remove:

* :func:`validate` — the fixtures and the schema are well-formed. Deterministic,
  runs in CI, and proves **nothing about the reviewer's recall**.
* :func:`grade` — a captured set of reviewer verdicts is compared against the
  expected ones. This is the measurement. It needs an LLM run, so it is a
  manual command, not a CI job.

A validation pass must never be reported as an eval pass. The names, the exit
messages and the README all say so, because the temptation to conflate them is
exactly what a green check invites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from oversteward.review_verdict import BLOCK, PASS, VERDICTS, parse_verdict

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_COULD_NOT_LOOK = 2

DIFF_NAME = "input.diff"
EXPECTED_NAME = "expected.json"

_REQUIRED_KEYS = frozenset(
    {
        "verdict",
        "failure_class",
        "catalogue_items",
        "must_cite",
        "must_mention",
        "provenance",
        "reconstructed",
        "why",
    }
)

#: Below this the eval stops discriminating: a set of one block and one pass
#: can be satisfied by a coin. OS#428 asks for at least five known-bad cases.
MIN_BLOCK_CASES = 5


class EvalSetError(RuntimeError):
    """The eval set itself is unusable, so nothing measured against it means anything."""


@dataclass(frozen=True)
class Case:
    """One eval case: a diff, and the verdict a working reviewer must return."""

    name: str
    diff: str
    expected: dict

    @property
    def expected_verdict(self) -> str:
        return self.expected["verdict"]


def load_cases(root: Path) -> list[Case]:
    """Every case directory under ``root``, sorted. Raises when one is unusable."""
    if not root.is_dir():
        raise EvalSetError(f"no eval directory at {root}")
    cases = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        diff_path = directory / DIFF_NAME
        expected_path = directory / EXPECTED_NAME
        missing = [p.name for p in (diff_path, expected_path) if not p.is_file()]
        if missing:
            raise EvalSetError(f"{directory.name}: missing {', '.join(missing)}")
        try:
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalSetError(f"{directory.name}/{EXPECTED_NAME}: {exc}") from exc
        cases.append(
            Case(
                name=directory.name,
                diff=diff_path.read_text(encoding="utf-8"),
                expected=expected,
            )
        )
    if not cases:
        raise EvalSetError(f"{root} contains no case directories — an empty eval proves nothing")
    return cases


def _validate_case(case: Case) -> list[str]:
    problems = []
    missing = _REQUIRED_KEYS - set(case.expected)
    if missing:
        problems.append(f"{case.name}: expected.json missing {', '.join(sorted(missing))}")
        return problems
    if case.expected_verdict not in VERDICTS:
        problems.append(
            f"{case.name}: unknown expected verdict {case.expected_verdict!r}"
        )
    if not case.diff.strip():
        problems.append(f"{case.name}: {DIFF_NAME} is empty")
    if not str(case.expected["why"]).strip():
        problems.append(f"{case.name}: 'why' is empty — a case nobody can grade by hand")
    for path in case.expected["must_cite"]:
        if path not in case.diff:
            problems.append(
                f"{case.name}: must_cite {path!r} does not appear in {DIFF_NAME}; "
                "the reviewer is being asked to cite a file it will never see"
            )
    if case.expected_verdict == PASS and case.expected["must_cite"]:
        problems.append(f"{case.name}: a PASS control must not require citations")
    if case.expected_verdict != PASS and not case.expected["must_cite"]:
        problems.append(
            f"{case.name}: a known-bad case must name the file the reviewer has to cite, "
            "or 'caught it' cannot be distinguished from 'blocked something'"
        )
    return problems


def validate(cases: list[Case]) -> list[str]:
    """Everything wrong with the eval set. Empty means well-formed — not 'reviewer works'."""
    problems = [problem for case in cases for problem in _validate_case(case)]
    blocks = [c for c in cases if c.expected_verdict == BLOCK]
    passes = [c for c in cases if c.expected_verdict == PASS]
    if len(blocks) < MIN_BLOCK_CASES:
        problems.append(
            f"only {len(blocks)} BLOCK cases; OS#428 requires at least {MIN_BLOCK_CASES}"
        )
    if not passes:
        problems.append(
            "no PASS control — without one, a reviewer that blocks every diff scores "
            "perfectly and the eval measures nothing"
        )
    return problems


@dataclass(frozen=True)
class GradedCase:
    """One case's outcome: what was expected, what the reviewer said, and why it counted."""

    name: str
    expected: str
    actual: str | None
    caught: bool
    note: str


def grade_case(case: Case, reviewer_output: str | None) -> GradedCase:
    """Compare one reviewer output against the case's expectation."""
    if reviewer_output is None:
        return GradedCase(case.name, case.expected_verdict, None, False, "no result captured")
    try:
        verdict = parse_verdict(reviewer_output)
    except RuntimeError as exc:
        return GradedCase(
            case.name, case.expected_verdict, None, False, f"unparseable verdict: {exc}"
        )

    if case.expected_verdict == PASS:
        caught = verdict.verdict == PASS
        note = "clean control passed" if caught else "blocked the clean control"
        return GradedCase(case.name, PASS, verdict.verdict, caught, note)

    if verdict.verdict != BLOCK:
        return GradedCase(
            case.name,
            case.expected_verdict,
            verdict.verdict,
            False,
            f"expected BLOCK, got {verdict.verdict}",
        )
    uncited = [p for p in case.expected["must_cite"] if p not in reviewer_output]
    if uncited:
        return GradedCase(
            case.name,
            case.expected_verdict,
            verdict.verdict,
            False,
            f"blocked, but never cited {', '.join(uncited)} — blocked for another reason",
        )
    return GradedCase(case.name, case.expected_verdict, verdict.verdict, True, "caught")


def grade(cases: list[Case], results: dict[str, str | None]) -> list[GradedCase]:
    """Grade every case against a mapping of case name to captured reviewer output."""
    return [grade_case(case, results.get(case.name)) for case in cases]
