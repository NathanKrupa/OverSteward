# ABOUTME: MIDDLE service for epic health — groups issues into epics and judges each one.
# ABOUTME: Surfaces the line of inquiry that dropped from the queue, not merely the count.

"""Epic health: which lines of inquiry have silently stopped moving.

GS reached 200+ open issues with 27 epics that were only label prefixes and no
way to tell which described problems already fixed (2026-08-28). A count of open
issues cannot show a forgotten epic; this model can. An epic here is a
``epic:<slug>`` label (its *parent* is the epic-titled issue carrying that
label, when one exists) or an epic-titled issue with no slug label (keyed
``#N``, children named only in its body). Motion is measured on the children:
a parent's ``updatedAt`` moves on every label tweak, so it is ignored.

Closed children are visible only when they carry the slug label — the client
fetches closed issues by label, so a body-mentioned child that closed without
the label is not counted.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from oversteward.board.models import Issue

#: No child has moved for this many days: worth a glance.
QUIET_AFTER_DAYS = 14
#: No child has moved for this many days: the line has dropped from the queue.
STALLED_AFTER_DAYS = 30


class EpicHealth(Enum):
    """One epic's verdict. Everything but ACTIVE and QUIET wants a decision."""

    ACTIVE = "active"
    QUIET = "quiet"
    STALLED = "stalled"
    #: Children carry the label; no epic issue exists to hold the line of inquiry.
    LABEL_ONLY = "label-only"
    #: The parent was closed while children remain open.
    PARENT_CLOSED = "parent-closed"
    #: An open parent whose every child is closed: finished, never closed.
    DONE_OPEN = "done-open"
    #: An open parent with no children at all: a line of inquiry never broken down.
    CHILDLESS = "childless"


#: Verdicts that ask Nathan for a decision rather than report motion.
DECISION_HEALTH = frozenset({
    EpicHealth.STALLED,
    EpicHealth.LABEL_ONLY,
    EpicHealth.PARENT_CLOSED,
    EpicHealth.DONE_OPEN,
    EpicHealth.CHILDLESS,
})


@dataclass(frozen=True, slots=True)
class Epic:
    """One epic: its parent (if any), its children, and what they say about it."""

    repo: str
    #: ``epic:<slug>`` for a labelled epic; ``#<number>`` for a title-only one.
    key: str
    parent: Issue | None
    children: tuple[Issue, ...]

    @property
    def open_children(self) -> int:
        return sum(1 for c in self.children if c.is_open)

    @property
    def closed_children(self) -> int:
        return len(self.children) - self.open_children

    @property
    def last_motion(self) -> datetime | None:
        """The freshest child event, close or update. ``None`` without children."""
        if not self.children:
            return None
        return max(c.last_motion for c in self.children)

    @property
    def last_motion_was_close(self) -> bool:
        """True when the most recent thing to happen on this epic was a child closing."""
        if not self.children:
            return False
        freshest = max(self.children, key=lambda c: c.last_motion)
        return not freshest.is_open

    def days_quiet(self, now: datetime) -> int | None:
        motion = self.last_motion
        if motion is None:
            return None
        return int((now - motion).total_seconds() // 86400)

    def health(self, now: datetime) -> EpicHealth:
        if self.parent is None:
            return EpicHealth.LABEL_ONLY
        if not self.children:
            return EpicHealth.CHILDLESS
        if not self.parent.is_open:
            return EpicHealth.PARENT_CLOSED
        if self.open_children == 0:
            return EpicHealth.DONE_OPEN
        quiet = self.days_quiet(now)
        if quiet is not None and quiet >= STALLED_AFTER_DAYS:
            return EpicHealth.STALLED
        if quiet is not None and quiet >= QUIET_AFTER_DAYS:
            return EpicHealth.QUIET
        return EpicHealth.ACTIVE

    @property
    def title(self) -> str:
        return self.parent.title if self.parent else self.key


def build_epics(issues: Iterable[Issue]) -> tuple[Epic, ...]:
    """Group every issue into the epics it belongs to.

    An epic with no open parent and no open child is finished and omitted —
    the board shows the living estate, not its history. Everything else is
    returned, sorted by repo then key, so the caller can judge each one.
    """
    by_repo: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_repo[issue.repo].append(issue)

    epics: list[Epic] = []
    for repo, repo_issues in sorted(by_repo.items()):
        by_number = {i.number: i for i in repo_issues}
        parents_by_key: dict[str, Issue] = {}
        children_by_key: dict[str, dict[int, Issue]] = defaultdict(dict)

        for issue in repo_issues:
            if issue.is_epic:
                keys = issue.epic_slugs or frozenset({f"#{issue.number}"})
                for key in keys:
                    # An open parent wins over a closed one carrying the same slug.
                    incumbent = parents_by_key.get(key)
                    if incumbent is None or (issue.is_open and not incumbent.is_open):
                        parents_by_key[key] = issue
            else:
                for key in issue.epic_slugs:
                    children_by_key[key][issue.number] = issue

        for key, parent in parents_by_key.items():
            for ref in parent.body_refs:
                child = by_number.get(ref)
                if child is not None and child is not parent and not child.is_epic:
                    children_by_key[key].setdefault(ref, child)

        for key in sorted(set(parents_by_key) | set(children_by_key)):
            parent = parents_by_key.get(key)
            children = tuple(sorted(children_by_key[key].values(), key=lambda c: c.number))
            parent_open = parent is not None and parent.is_open
            if not parent_open and all(not c.is_open for c in children):
                continue
            epics.append(Epic(repo=repo, key=key, parent=parent, children=children))
    return tuple(epics)


__all__ = [
    "DECISION_HEALTH",
    "QUIET_AFTER_DAYS",
    "STALLED_AFTER_DAYS",
    "Epic",
    "EpicHealth",
    "build_epics",
]
