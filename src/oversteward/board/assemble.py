# ABOUTME: MIDDLE service that assembles the Estate Board — the decision queue and the counts.
# ABOUTME: Shows only what wants a decision from Nathan plus counts; the rest stays in /project-status.

"""Assemble the board from every repository's issues.

The board is not a Linear clone. It shows two things: **decisions** — the
questions agents are waiting on, and the epics whose health asks for a ruling
— and **counts** per repository so the decisions have scale beside them.
Everything else (in-flight PRs, 30-day metrics) is ``/project-status``'s.

A decision is a plain record: where to look, what is being asked, how long it
has waited — and which verbs answer it. A verb is a GitHub write the page makes
through the connector (a comment plus a label swap or a state change); the
decision names the issue it aims at, so the page never derives a target from
text. A decision with no issue to write to (a label-only epic) offers none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from urllib.parse import quote

from oversteward.board.epics import DECISION_HEALTH, Epic, EpicHealth, build_epics
from oversteward.board.models import (
    AGENT_IN_PROGRESS,
    NEEDS_INPUT,
    NEEDS_SCOPING,
    READY_FOR_AGENT,
    Issue,
)

#: A question an agent asked more than this long ago is stale — the dispatch is
#: parked and the agent's context is gone.
STALE_ANSWER_HOURS = 48

#: Epic verdicts in the order they are shown: the ones a wrong state produced
#: before the ones mere time produced.
_EPIC_ORDER = (
    EpicHealth.PARENT_CLOSED,
    EpicHealth.DONE_OPEN,
    EpicHealth.STALLED,
    EpicHealth.LABEL_ONLY,
    EpicHealth.CHILDLESS,
)


class DecisionKind(Enum):
    ANSWER = "answer"
    EPIC = "epic"


class Verb(Enum):
    """A write the page can make on a decision's issue.

    Each verb is one comment carrying the ruling plus one state change:
    ``ANSWER`` swaps ``needs-input`` for ``ready-for-agent`` in the exact form
    ``/answer`` uses, so the re-dispatch reads it alike; ``CLOSE`` closes as
    completed; ``SHELVE`` closes as not planned; ``REOPEN`` reopens.
    """

    ANSWER = "answer"
    CLOSE = "close"
    SHELVE = "shelve"
    REOPEN = "reopen"


@dataclass(frozen=True, slots=True)
class Action:
    """One tappable verb: what the button says and what the note box asks for."""

    verb: Verb
    label: str
    prompt: str
    #: A ruling that needs its reason on the record cannot be tapped blank.
    note_required: bool


@dataclass(frozen=True, slots=True)
class Target:
    """The GitHub issue a decision's verbs write to."""

    owner: str
    repo: str
    number: int

    @classmethod
    def from_url(cls, url: str) -> Target | None:
        match = _ISSUE_URL.match(url)
        if match is None:
            return None
        return cls(owner=match[1], repo=match[2], number=int(match[3]))


_ISSUE_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)$")

_ANSWER_ACTION = Action(
    Verb.ANSWER, "Answer", "Your answer to the agent's question", note_required=True
)

#: The verb each epic verdict offers. A ruling that ends a line of inquiry
#: (shelving) must say why; closing a finished epic or reopening an abandoned
#: one needs no reason beyond the verdict itself.
_EPIC_ACTIONS: dict[EpicHealth, tuple[Action, ...]] = {
    EpicHealth.DONE_OPEN: (
        Action(Verb.CLOSE, "Close the epic", "Note for the record (optional)", note_required=False),
    ),
    EpicHealth.PARENT_CLOSED: (
        Action(Verb.REOPEN, "Reopen the epic", "Why it reopens (optional)", note_required=False),
    ),
    EpicHealth.STALLED: (
        Action(Verb.SHELVE, "Shelve", "Why this line of inquiry is shelved", note_required=True),
    ),
    EpicHealth.CHILDLESS: (
        Action(Verb.SHELVE, "Close it", "Why this epic closes unbroken", note_required=True),
    ),
    EpicHealth.LABEL_ONLY: (),
}


@dataclass(frozen=True, slots=True)
class Decision:
    """One thing waiting on Nathan."""

    kind: DecisionKind
    repo: str
    #: ``#N`` for an issue, ``epic:<slug>`` for a labelled epic.
    ref: str
    title: str
    url: str
    #: What is being asked, in one line.
    ask: str
    age_days: int
    stale: bool = False
    #: The issue the verbs write to; ``None`` when there is no issue (label-only epic).
    target: Target | None = None
    actions: tuple[Action, ...] = ()


@dataclass(frozen=True, slots=True)
class RepoCounts:
    repo: str
    open: int
    needs_input: int
    ready: int
    in_progress: int
    needs_scoping: int
    epics: int


@dataclass(frozen=True, slots=True)
class BoardReport:
    generated_at: datetime
    repos: tuple[RepoCounts, ...]
    decisions: tuple[Decision, ...]
    epics: tuple[Epic, ...]


def _days(since: datetime, now: datetime) -> int:
    return int((now - since).total_seconds() // 86400)


def _counts(repo: str, issues: Sequence[Issue], epics: Sequence[Epic]) -> RepoCounts:
    open_issues = [i for i in issues if i.is_open]
    return RepoCounts(
        repo=repo,
        open=len(open_issues),
        needs_input=sum(NEEDS_INPUT in i.labels for i in open_issues),
        ready=sum(READY_FOR_AGENT in i.labels for i in open_issues),
        in_progress=sum(AGENT_IN_PROGRESS in i.labels for i in open_issues),
        needs_scoping=sum(NEEDS_SCOPING in i.labels for i in open_issues),
        epics=len(epics),
    )


def _answer_decision(issue: Issue, now: datetime) -> Decision:
    hours = (now - issue.updated_at).total_seconds() / 3600
    return Decision(
        kind=DecisionKind.ANSWER,
        repo=issue.repo,
        ref=f"#{issue.number}",
        title=issue.title,
        url=issue.url,
        ask="Answer the agent's question",
        age_days=_days(issue.updated_at, now),
        stale=hours >= STALE_ANSWER_HOURS,
        target=Target.from_url(issue.url),
        actions=(_ANSWER_ACTION,),
    )


def _label_search_url(child: Issue, key: str) -> str:
    """The repository's open issues carrying the label — the only page a label-only epic has."""
    repo_url = child.url.rsplit("/issues/", 1)[0]
    return f"{repo_url}/issues?q=" + quote(f'is:open label:"{key}"', safe="")


def _epic_ask(epic: Epic, health: EpicHealth, now: datetime) -> str:
    if health is EpicHealth.PARENT_CLOSED:
        return f"Epic closed with {epic.open_children} children open — reopen it, or close them"
    if health is EpicHealth.DONE_OPEN:
        return f"Every child is closed ({epic.closed_children}) — close the epic"
    if health is EpicHealth.STALLED:
        return f"No child has moved in {epic.days_quiet(now)} days — revive or shelve"
    if health is EpicHealth.LABEL_ONLY:
        return f"{epic.open_children} open issues carry {epic.key} but no epic holds them — file one, or retire the label"
    return "Epic with no children — break it into issues, or close it"


def _epic_decision(epic: Epic, now: datetime) -> Decision:
    health = epic.health(now)
    if epic.parent is not None:
        url = epic.parent.url
    else:
        url = _label_search_url(epic.children[0], epic.key)
    quiet = epic.days_quiet(now)
    parent = epic.parent
    return Decision(
        kind=DecisionKind.EPIC,
        repo=epic.repo,
        ref=epic.key,
        title=epic.title,
        url=url,
        ask=_epic_ask(epic, health, now),
        age_days=quiet if quiet is not None else _days(epic.parent.created_at, now),
        target=None if parent is None else Target.from_url(parent.url),
        actions=_EPIC_ACTIONS[health],
    )


def assemble(issues_by_repo: Mapping[str, Sequence[Issue]], *, now: datetime) -> BoardReport:
    """One report: counts per repo in the order given, decisions queued oldest-question-first."""
    epics_by_repo = {repo: build_epics(issues) for repo, issues in issues_by_repo.items()}
    repos = tuple(
        _counts(repo, issues, epics_by_repo[repo]) for repo, issues in issues_by_repo.items()
    )

    answers = sorted(
        (
            _answer_decision(i, now)
            for issues in issues_by_repo.values()
            for i in issues
            if i.is_open and NEEDS_INPUT in i.labels
        ),
        key=lambda d: -d.age_days,
    )
    epic_decisions = [
        (
            _EPIC_ORDER.index(epic.health(now)),
            -(epic.days_quiet(now) or 0),
            _epic_decision(epic, now),
        )
        for epics in epics_by_repo.values()
        for epic in epics
        if epic.health(now) in DECISION_HEALTH
    ]
    epic_decisions.sort(key=lambda row: row[:2])

    return BoardReport(
        generated_at=now,
        repos=repos,
        decisions=(*answers, *(row[2] for row in epic_decisions)),
        epics=tuple(e for epics in epics_by_repo.values() for e in epics),
    )


__all__ = [
    "STALE_ANSWER_HOURS",
    "Action",
    "BoardReport",
    "Decision",
    "DecisionKind",
    "RepoCounts",
    "Target",
    "Verb",
    "assemble",
]
