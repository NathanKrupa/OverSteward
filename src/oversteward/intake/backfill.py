# ABOUTME: The one-time intake backfill — classify every open issue, report, and plan label adds.
# ABOUTME: The plan only adds labels an issue lacks; applying it is a separate, explicit step.

"""Classify the open backlog once, so the intake split starts from a labelled estate.

The report is what Nathan reads before anything is applied (OS#613): counts per
repository per class, and a seeded random sample of each class with its title,
proposal and reason. ``plan`` turns the proposals into label additions; it never
removes a label, so re-running it after a partial apply is safe. Given ``only``,
the plan adds only those labels and the report's header says so. Without it the
plan still adds every proposed label, ``agent-finding`` included: Nathan's ruling
that the existing backlog gets ``tribe`` and never ``agent-finding`` (OS#620) is
kept only by passing ``--only tribe``; nothing here enforces it.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from oversteward.intake.classify import UNCLASSIFIED, Proposal, classify
from oversteward.intake.labels import AGENT_FINDING, TRIBE
from oversteward.intake.models import IntakeIssue

CLASSES = (TRIBE, AGENT_FINDING, f"{TRIBE}+{AGENT_FINDING}", UNCLASSIFIED)
#: The labels a plan may be restricted to.
LABELS = (TRIBE, AGENT_FINDING)


@dataclass(frozen=True, slots=True)
class Row:
    issue: IntakeIssue
    proposal: Proposal

    @property
    def to_add(self) -> tuple[str, ...]:
        return tuple(sorted(self.proposal.labels - self.issue.labels))


@dataclass(frozen=True, slots=True)
class Step:
    repo: str
    number: int
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Failure:
    step: Step
    error: str


def classify_all(issues: Iterable[IntakeIssue]) -> list[Row]:
    return [Row(issue, classify(issue)) for issue in issues]


def count_by_repo(rows: Iterable[Row]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        counts.setdefault(row.issue.repo, Counter())[row.proposal.klass] += 1
    return counts


def sample_by_class(rows: list[Row], *, per_class: int, seed: int) -> dict[str, list[Row]]:
    """Up to ``per_class`` rows of each class, drawn reproducibly from ``seed``."""
    rng = random.Random(seed)
    samples: dict[str, list[Row]] = {}
    for klass in CLASSES:
        members = [r for r in rows if r.proposal.klass == klass]
        samples[klass] = members if len(members) <= per_class else rng.sample(members, per_class)
    return samples


def plan(rows: Iterable[Row], *, only: frozenset[str] | None = None) -> list[Step]:
    """One step per issue missing a proposed label; with ``only``, other labels are dropped."""
    steps = []
    for row in rows:
        labels = row.to_add
        if only is not None:
            labels = tuple(label for label in labels if label in only)
        if labels:
            steps.append(Step(row.issue.repo, row.issue.number, labels))
    return steps


def apply_plan(
    steps: Iterable[Step], add: Callable[[str, int, tuple[str, ...]], object]
) -> list[Failure]:
    """Add each step's labels; keep going past a failure and return every one."""
    failures: list[Failure] = []
    for step in steps:
        try:
            add(step.repo, step.number, step.labels)
        except Exception as exc:  # noqa: BLE001 — every failure is reported, none swallowed
            failures.append(Failure(step, str(exc)))
    return failures


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _filter_lines(only: frozenset[str] | None) -> list[str]:
    if only is None:
        return []
    flags = " ".join(f"--only {label}" for label in sorted(only))
    return [
        f"Filter: `{flags}` — the plan adds only these labels. The counts and samples below "
        "show every proposal; the rest are not applied.",
        "",
    ]


def render_report(
    rows: list[Row],
    *,
    per_class: int,
    seed: int,
    generated: str,
    only: frozenset[str] | None = None,
) -> str:
    counts = count_by_repo(rows)
    steps = plan(rows, only=only)
    lines = [
        f"# Intake backfill — dry run ({generated})",
        "",
        f"{len(rows)} open issues read across {len(counts)} repositories. Deterministic rules only "
        "(labels, agent body markers, title shapes, repo); no LLM call. Nothing has been applied.",
        "",
        *_filter_lines(only),
        f"`--apply` would add labels to {len(steps)} issues "
        f"({sum(len(s.labels) for s in steps)} label additions); it never removes a label.",
        "",
        "## Counts per repository",
        "",
        "| repo | " + " | ".join(CLASSES) + " | total |",
        "|---|" + "---|" * (len(CLASSES) + 1),
    ]
    for repo in sorted(counts):
        cells = [str(counts[repo].get(k, 0)) for k in CLASSES]
        lines.append(f"| {repo} | " + " | ".join(cells) + f" | {sum(counts[repo].values())} |")
    totals = Counter(r.proposal.klass for r in rows)
    lines.append(
        "| **all** | " + " | ".join(f"**{totals.get(k, 0)}**" for k in CLASSES) + f" | **{len(rows)}** |"
    )
    samples = sample_by_class(rows, per_class=per_class, seed=seed)
    for klass in CLASSES:
        lines += ["", f"## Sample: {klass}", ""]
        if not samples[klass]:
            lines.append("_none in this class_")
            continue
        lines += ["| issue | title | proposed | reason |", "|---|---|---|---|"]
        for row in samples[klass]:
            lines.append(
                f"| {row.issue.repo}#{row.issue.number} | {_cell(row.issue.title)} | "
                f"{row.proposal.klass} | {_cell('; '.join(row.proposal.reasons))} |"
            )
    lines += ["", f"_Sample seed {seed}, up to {per_class} rows per class._", ""]
    return "\n".join(lines)
