# ABOUTME: Tribe-first ranking of a repository's issues and the displaced-tribe dispatch notice.
# ABOUTME: Pure: takes IntakeIssues, returns ordered tuples and printable text.

"""Rank work so ``tribe`` comes first (OS#613).

Nathan ruled on 2026-10-21 that a ``tribe`` issue — one a food-pantry user of
AI Grant Helper would notice — outranks every other issue, a paying consulting
client's ask included. Within each class the oldest issue goes first.

Dispatching a non-``tribe`` issue while a ``tribe`` issue is ready in the same
repository is allowed; it prints the items it passes over, so the choice is
seen rather than made by default.
"""

from __future__ import annotations

from collections.abc import Iterable

from oversteward.intake.labels import (
    AGENT_IN_PROGRESS,
    NEEDS_INPUT,
    NEEDS_SCOPING,
    READY_FOR_AGENT,
    REJECT_CLOSE,
    SHELVED,
    TRIBE,
)
from oversteward.intake.models import IntakeIssue

#: Labels that take a ready issue out of the dispatch queue.
DISPATCH_BLOCKERS = frozenset({AGENT_IN_PROGRESS, NEEDS_INPUT, NEEDS_SCOPING, REJECT_CLOSE, SHELVED})


def is_tribe(issue: IntakeIssue) -> bool:
    return TRIBE in issue.labels


def rank(issues: Iterable[IntakeIssue]) -> tuple[IntakeIssue, ...]:
    """``tribe`` first; oldest first within each class; issue number breaks a tie."""
    return tuple(sorted(issues, key=lambda i: (not is_tribe(i), i.created_at, i.number)))


def is_dispatchable(issue: IntakeIssue) -> bool:
    return READY_FOR_AGENT in issue.labels and not issue.labels & DISPATCH_BLOCKERS


def dispatch_queue(issues: Iterable[IntakeIssue]) -> tuple[IntakeIssue, ...]:
    """The ready-for-agent issues a dispatch may take, in the order it should take them."""
    return rank(i for i in issues if is_dispatchable(i))


def displaced_by(target: IntakeIssue, issues: Iterable[IntakeIssue]) -> tuple[IntakeIssue, ...]:
    """The ready ``tribe`` issues a dispatch of ``target`` passes over; none for a tribe target."""
    if is_tribe(target):
        return ()
    return tuple(
        i for i in dispatch_queue(issues) if is_tribe(i) and i.number != target.number
    )


def render_displacement(
    repo: str, target: IntakeIssue, displaced: tuple[IntakeIssue, ...]
) -> str:
    """A notice, never a refusal: it names what the dispatch passes over, or says nothing is."""
    if not displaced:
        kind = "tribe" if is_tribe(target) else "not tribe"
        return f"tribe check: {repo}#{target.number} ({kind}) — 0 ready tribe issues displaced.\n"
    lines = [
        f"TRIBE DISPLACED: dispatching {repo}#{target.number} (not tribe) passes over "
        f"{len(displaced)} ready tribe issue(s) in {repo}:"
    ]
    lines += [f"  - #{i.number} {i.title}  {i.url}" for i in displaced]
    lines.append("Proceeding is allowed; name the reason in the dispatch report.")
    return "\n".join(lines) + "\n"


def render_queue(repo: str, queue: tuple[IntakeIssue, ...]) -> str:
    lines = [f"{repo}: {len(queue)} ready-for-agent issue(s), tribe first"]
    lines += [
        f"  {'[tribe] ' if is_tribe(i) else ''}#{i.number} {i.title}  {i.url}" for i in queue
    ]
    return "\n".join(lines) + "\n"
