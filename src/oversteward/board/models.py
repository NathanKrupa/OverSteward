# ABOUTME: Typed shapes for the Estate Board — one GitHub issue as the board reads it.
# ABOUTME: Label vocabulary and the epic-title rule live here so every service reads them alike.

"""What a GitHub issue is to the board.

The board is derived entirely from GitHub issues — labels, titles, bodies and
timestamps — and never from its own state. This module fixes the vocabulary
those derivations share: which labels mean an issue is already spoken for,
which title shape marks an epic, and how an epic's children are named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

#: Prefix of the label that files an issue under an epic: ``epic:<slug>``.
EPIC_LABEL_PREFIX = "epic:"

#: An epic is an issue whose title announces it: ``Epic: …`` or ``epic(scope): …``.
_EPIC_TITLE = re.compile(r"^\s*epic\b", re.IGNORECASE)

#: ``#123`` mentions in a body — an epic's checklist names its children this way.
_ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")

#: An issue is waiting on Nathan when the agent that worked it asked a question.
NEEDS_INPUT = "needs-input"
READY_FOR_AGENT = "ready-for-agent"
AGENT_IN_PROGRESS = "agent-in-progress"

#: Issues carrying any of these labels are not "scoping candidates" — they are
#: already processed, in flight, declined, or deliberately deferred.
UNSCOPED_EXCLUDES = frozenset({
    READY_FOR_AGENT,
    AGENT_IN_PROGRESS,
    "agent-done",
    "reject-close",
    NEEDS_INPUT,
    "wontfix",
    "duplicate",
    "invalid",
    "backlog",
})


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class Issue:
    """One issue as ``gh issue list --json`` reports it, in the board's terms."""

    repo: str
    number: int
    title: str
    url: str
    state: str
    labels: frozenset[str]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    #: Issue numbers this body mentions as ``#N``; for an epic, its checklist.
    body_refs: frozenset[int]

    @classmethod
    def from_gh(cls, repo: str, raw: dict) -> Issue:
        updated = _parse_iso(raw.get("updatedAt"))
        created = _parse_iso(raw.get("createdAt")) or updated
        if updated is None:
            raise ValueError(f"{repo}#{raw.get('number')}: no updatedAt")
        return cls(
            repo=repo,
            number=int(raw["number"]),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            state=raw.get("state", "OPEN").upper(),
            labels=frozenset(label["name"] for label in raw.get("labels", ())),
            created_at=created,
            updated_at=updated,
            closed_at=_parse_iso(raw.get("closedAt")),
            body_refs=frozenset(int(n) for n in _ISSUE_REF.findall(raw.get("body") or "")),
        )

    @property
    def is_open(self) -> bool:
        return self.state == "OPEN"

    @property
    def is_epic(self) -> bool:
        return bool(_EPIC_TITLE.match(self.title))

    @property
    def epic_slugs(self) -> frozenset[str]:
        """Every ``epic:<slug>`` label on this issue, prefix included."""
        return frozenset(label for label in self.labels if label.startswith(EPIC_LABEL_PREFIX))

    @property
    def last_motion(self) -> datetime:
        """When this issue last did anything: its close, else its last update."""
        return self.closed_at or self.updated_at


__all__ = [
    "AGENT_IN_PROGRESS",
    "EPIC_LABEL_PREFIX",
    "Issue",
    "NEEDS_INPUT",
    "READY_FOR_AGENT",
    "UNSCOPED_EXCLUDES",
]
