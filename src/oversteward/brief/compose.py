# ABOUTME: MIDDLE service for the Estate Brief — decides what shipped, the one ask, and what is URGENT.
# ABOUTME: Renders a short plain-markdown note a vault-only skill reads aloud; it never writes a file.

"""Compose the nightly Estate Brief.

The brief is read aloud at the morning check-in by a skill that can only read
vault files, so it says four things and nothing else:

* **URGENT** — a Railway service that is down or in a state nothing
  classifies, or a liveness sweep that could not look. Rendered only when
  there is something to say. A service whose failure is already filed is
  marked ``KNOWN→<repo>#n`` — only through an exact ``<context>/<service>`` key
  recorded in ``data/known_failures.yaml``, and only while that issue is open;
  never by matching titles. Sentry is not read yet.
* **Shipped** — pull requests *merged* in the window, grouped by repository,
  with a count. A pull request closed without merging never counts, and
  ``0 shipped`` is a measured answer, not a missing one.
* **The one ask** — at most one ``needs-input`` issue: the oldest open one,
  with its latest ``@nathankrupa question:`` comment (else its body), trimmed,
  so the check-in can put the question word for word. With no ask waiting, the
  longest-idle Incubator candidate from the sweep is offered instead. Every
  other ask stays out of the note by design.
* **Shelved overnight** — what the abandoned-work sweep's ledger says it did in
  the window. A dry-run line renders as "would …", never as a thing done; a
  window with no completed sweep run says so rather than "nothing shelved".

GitHub failures propagate: a brief missing a repository is a smaller estate
than exists. A liveness sweep that could not look, or had nothing configured to
look at, does not stop the brief — the note still ships, naming the gap under
URGENT — but the brief records which of the two it was, so the caller can give
each its own exit code.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from oversteward.board.client import read_estate
from oversteward.board.config import RepoRef
from oversteward.board.models import Issue
from oversteward.brief.client import (
    AskThread,
    PullRequest,
    RepoActivity,
    read_activity,
    read_thread,
)
from oversteward.liveness.check import ProjectRef, sweep
from oversteward.liveness.client import RailwayConfigError, RailwayUnavailableError
from oversteward.liveness.models import LivenessReport
from oversteward.shelve.ledger import MODE_APPLIED, LedgerEntry
from oversteward.shelve.sweep import (
    RULE_BRANCH,
    RULE_INCUBATOR,
    RULE_PR_UNJUDGED,
    RULE_RUN,
    RULE_WORKTREE,
    VERB_FAILED,
    WRITE_VERBS,
    said,
)

#: Merged pull requests listed per repository before the rest collapse to ``+N more``.
SHIPPED_PER_REPO = 3
#: Shelving lines listed before the rest collapse to ``+N more``.
SHELVED_LISTED = 5
#: The comment prefix a dispatched agent asks Nathan with (``/answer`` reads the same).
QUESTION_MARKER = "@nathankrupa question:"
#: Characters of the question kept under the ask's link.
QUESTION_CHARS = 600

_KNOWN_ISSUE = re.compile(r"^([a-z0-9][a-z0-9-]*)#(\d+)$")

ActivityReader = Callable[[RepoRef, datetime], RepoActivity]
UrgentReader = Callable[[], Sequence[str]]
ThreadReader = Callable[[RepoRef, int], AskThread]
ShelvedReader = Callable[[], Sequence[LedgerEntry]]


class UrgentRead(Enum):
    """How the URGENT source answered. The two failures must never print the same."""

    MEASURED = "measured"
    #: The sweep ran and could not look: Railway unreachable or unreadable.
    BLIND = "blind"
    #: Nothing was configured to look at: no context carries a ``railway:`` block.
    UNCONFIGURED = "unconfigured"


class ShelvedRead(Enum):
    """How the sweep ledger answered. Each prints differently."""

    MEASURED = "measured"
    #: The ledger holds no completed sweep run inside the window.
    NO_RUN = "no-run"
    #: The ledger exists and could not be read or parsed.
    UNREADABLE = "unreadable"
    #: No ledger path was given.
    UNCONFIGURED = "unconfigured"


@dataclass(frozen=True, slots=True)
class Shelved:
    read: ShelvedRead
    #: Window entries, latest per item, run lines excluded.
    entries: tuple[LedgerEntry, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class KnownIssue:
    """A recorded issue for one failing service: registry id and issue number."""

    repo: str
    number: int

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}"


def known_failures(data: Mapping[str, Any], repos: Sequence[RepoRef]) -> dict[str, KnownIssue]:
    """The ``railway:`` map of ``data/known_failures.yaml``, validated.

    Keys are ``<registry context id>/<service name>`` exactly as the liveness
    sweep names them; values are ``<registry id>#<issue>``. Anything else is a
    ``ValueError``, because a mapping that silently fails to match turns a known
    failure back into a fresh alarm, and one that matches loosely hides a new one.
    """
    ids = {repo.id for repo in repos}
    found: dict[str, KnownIssue] = {}
    for key, value in (data.get("railway") or {}).items():
        match = _KNOWN_ISSUE.match(str(value))
        if "/" not in str(key) or match is None or match[1] not in ids:
            raise ValueError(f"known_failures: {key!r}: {value!r} is not <context>/<service>: <repo>#<n>")
        found[str(key)] = KnownIssue(match[1], int(match[2]))
    return found


@dataclass(frozen=True, slots=True)
class Brief:
    generated_at: datetime
    window: timedelta
    #: ``(repo id, merged pull requests)`` for each repository that shipped, in registry order.
    shipped: tuple[tuple[str, tuple[PullRequest, ...]], ...]
    ask: Issue | None
    urgent: tuple[str, ...]
    #: Whether the URGENT lines are a measurement; when not, they name the gap.
    urgent_read: UrgentRead
    #: The ask's question, trimmed; ``None`` when there is no ask.
    question: str | None = None
    shelved: Shelved = Shelved(ShelvedRead.UNCONFIGURED)

    @property
    def shipped_count(self) -> int:
        return sum(len(pulls) for _, pulls in self.shipped)


def liveness_urgent(
    projects: Sequence[ProjectRef],
    *,
    sweeper: Callable[[Sequence[ProjectRef]], LivenessReport] = sweep,
    known: Mapping[str, KnownIssue] | None = None,
    is_open: Callable[[KnownIssue], bool] = lambda _issue: False,
) -> tuple[str, ...]:
    """One line per Railway service that is down or in a state nothing classifies.

    A service whose exact ``<project>/<service>`` key is in ``known`` and whose
    issue is still open is marked ``KNOWN→<repo>#n``; a recorded issue that has
    closed leaves the line a fresh alarm, saying so.
    """
    known = known or {}
    lines = []
    for state in sweeper(projects).findings:
        line = f"Railway: {state.project} / {state.name} is {state.status or 'in an unknown state'}"
        issue = known.get(f"{state.project}/{state.name}")
        if issue is not None and is_open(issue):
            line = f"KNOWN→{issue} — {line}"
        elif issue is not None:
            line = f"{line} (recorded issue {issue} is no longer open)"
        lines.append(line)
    return tuple(lines)


def question_text(thread: AskThread) -> str:
    """The latest ``@nathankrupa question:`` comment's text, else the body; trimmed."""
    asked = [c for c in thread.comments if QUESTION_MARKER in c.lower()]
    if asked:
        latest = asked[-1]
        text = latest[latest.lower().index(QUESTION_MARKER) + len(QUESTION_MARKER):]
    else:
        text = thread.body
    text = " ".join(text.split())
    if len(text) > QUESTION_CHARS:
        text = text[: QUESTION_CHARS - 1].rstrip() + "…"
    return text


def _shelved(read_shelved: ShelvedReader | None, since: datetime, now: datetime) -> Shelved:
    if read_shelved is None:
        return Shelved(ShelvedRead.UNCONFIGURED)
    try:
        entries = read_shelved()
    except FileNotFoundError as exc:
        return Shelved(ShelvedRead.NO_RUN, detail=f"no ledger at {exc.filename}")
    except (OSError, ValueError) as exc:
        return Shelved(ShelvedRead.UNREADABLE, detail=str(exc))
    window = [e for e in entries if since <= e.at <= now]
    latest: dict[tuple, LedgerEntry] = {}
    for entry in sorted(window, key=lambda e: e.at):
        if entry.rule != RULE_RUN:
            latest[(entry.mode, entry.repo, entry.kind, entry.number, entry.ref, entry.action)] = entry
    ran = any(e.rule == RULE_RUN for e in window)
    return Shelved(ShelvedRead.MEASURED if ran else ShelvedRead.NO_RUN, tuple(latest.values()))


def _merged_in_window(pulls: Sequence[PullRequest], since: datetime) -> tuple[PullRequest, ...]:
    shipped = [p for p in pulls if p.merged_at is not None and p.merged_at >= since]
    return tuple(sorted(shipped, key=lambda p: p.merged_at))


def _oldest_ask(activity: Sequence[RepoActivity]) -> Issue | None:
    asks = [issue for repo in activity for issue in repo.asks]
    if not asks:
        return None
    return min(asks, key=lambda issue: (issue.created_at, issue.repo, issue.number))


def _read_urgent(read_urgent: UrgentReader) -> tuple[tuple[str, ...], UrgentRead]:
    try:
        return tuple(read_urgent()), UrgentRead.MEASURED
    except RailwayConfigError as exc:
        return (f"Railway liveness is not configured — {exc}",), UrgentRead.UNCONFIGURED
    except RailwayUnavailableError as exc:
        return (f"Could not check Railway — {exc}",), UrgentRead.BLIND


def _question(ask: Issue | None, repos: Sequence[RepoRef], read: ThreadReader) -> str | None:
    if ask is None:
        return None
    repo = next(r for r in repos if r.id == ask.repo)
    return question_text(read(repo, ask.number))


def compose(
    repos: Sequence[RepoRef],
    *,
    now: datetime,
    window: timedelta,
    read_urgent: UrgentReader,
    read: ActivityReader = read_activity,
    read_thread: ThreadReader = read_thread,
    read_shelved: ShelvedReader | None = None,
) -> Brief:
    """Read every repository and decide what the brief says."""
    since = now - window
    by_repo = read_estate(repos, reader=lambda repo: read(repo, since))
    activity = list(by_repo.values())
    shipped = tuple(
        (repo_id, merged)
        for repo_id, merged in ((a.repo, _merged_in_window(a.pulls, since)) for a in activity)
        if merged
    )
    urgent, urgent_read = _read_urgent(read_urgent)
    ask = _oldest_ask(activity)
    return Brief(
        generated_at=now,
        window=window,
        shipped=shipped,
        ask=ask,
        urgent=urgent,
        urgent_read=urgent_read,
        question=_question(ask, repos, read_thread),
        shelved=_shelved(read_shelved, since, now),
    )


def _window_phrase(window: timedelta) -> str:
    hours = int(window.total_seconds() // 3600)
    return "the last 24 hours" if hours == 24 else f"the last {hours} hours"


def _shipped_lines(brief: Brief) -> list[str]:
    count = brief.shipped_count
    repos = len(brief.shipped)
    where = f" across {repos} repo{'s' if repos != 1 else ''}" if count else ""
    lines = ["## Shipped", "", f"{count} shipped{where} in {_window_phrase(brief.window)}."]
    for repo_id, pulls in brief.shipped:
        lines += ["", f"**{repo_id}** ({len(pulls)})"]
        lines.extend(f"- {p.title} (#{p.number})" for p in pulls[:SHIPPED_PER_REPO])
        if len(pulls) > SHIPPED_PER_REPO:
            lines.append(f"- +{len(pulls) - SHIPPED_PER_REPO} more")
    return lines


def _incubator_candidate(shelved: Shelved) -> LedgerEntry | None:
    candidates = [e for e in shelved.entries if e.rule == RULE_INCUBATOR]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (e.idle_days or 0, e.repo, -(e.number or 0)))


def _ask_lines(brief: Brief) -> list[str]:
    lines = ["## The one ask", ""]
    if brief.ask is not None:
        ask = brief.ask
        lines.append(f"[{ask.title}]({ask.url}) — {ask.repo} #{ask.number}")
        if brief.question:
            lines += ["", f"> {brief.question}"]
        return lines
    candidate = _incubator_candidate(brief.shelved)
    if candidate is None:
        lines.append("Nothing is waiting on you.")
    else:
        lines.append(
            f"Move to the Incubator? [{candidate.title}]({candidate.url}) — {candidate.repo} "
            f"#{candidate.number}, idle {candidate.idle_days} days."
        )
    return lines


_REPORTED = (
    (RULE_BRANCH, "branch with no pull request", "branches with no pull request"),
    (RULE_WORKTREE, "unlanded worktree", "unlanded worktrees"),
    (RULE_PR_UNJUDGED, "pull request too long to judge", "pull requests too long to judge"),
)


def _reported_line(entries: Sequence[LedgerEntry]) -> str | None:
    counts = Counter(e.rule for e in entries if e.action not in WRITE_VERBS)
    parts = [
        f"{counts[rule]} {one if counts[rule] == 1 else many}"
        for rule, one, many in _REPORTED
        if counts[rule]
    ]
    return f"Reported, untouched: {', '.join(parts)}." if parts else None


def _shelved_lines(brief: Brief) -> list[str]:
    shelved = brief.shelved
    lines = ["## Shelved overnight", ""]
    if shelved.read is ShelvedRead.UNCONFIGURED:
        return lines + ["No sweep ledger configured."]
    if shelved.read is ShelvedRead.UNREADABLE:
        return lines + [f"Could not read the sweep ledger — {shelved.detail}"]
    if shelved.read is ShelvedRead.NO_RUN:
        detail = f" ({shelved.detail})" if shelved.detail else ""
        lines += [f"The abandoned-work sweep did not finish a run in {_window_phrase(brief.window)}{detail}."]
    writes = [e for e in shelved.entries if e.action in WRITE_VERBS]
    if any(e.mode != MODE_APPLIED for e in writes):
        lines.append("Dry run — nothing below was changed on GitHub.")
    for entry in writes[:SHELVED_LISTED]:
        idle = f", idle {entry.idle_days}d" if entry.idle_days is not None else ""
        lines.append(f"- {said(entry)} {entry.repo} #{entry.number} — {entry.title}{idle}")
    if len(writes) > SHELVED_LISTED:
        lines.append(f"- +{len(writes) - SHELVED_LISTED} more")
    for entry in (e for e in shelved.entries if e.action == VERB_FAILED):
        lines.append(f"- gh failed ({entry.reason}) on {entry.repo} #{entry.number} — {entry.title}")
    if not writes and shelved.read is ShelvedRead.MEASURED:
        lines.append("Nothing shelved or reopened.")
    reported = _reported_line(shelved.entries)
    if reported:
        lines.append(reported)
    candidates = sum(1 for e in shelved.entries if e.rule == RULE_INCUBATOR)
    if candidates:
        lines.append(f"{candidates} issue{'s' if candidates != 1 else ''} idle 90+ days: Incubator candidates.")
    return lines


def render(brief: Brief) -> str:
    """The note, as plain markdown short enough to read aloud."""
    stamp = brief.generated_at
    lines = [
        "# Estate Brief",
        "",
        f"Date: {stamp:%Y-%m-%d} ({stamp:%A}), written at {stamp:%H:%M}.",
        "",
    ]
    if brief.urgent:
        lines += ["## URGENT", "", *(f"- {line}" for line in brief.urgent), ""]
    lines += _shipped_lines(brief)
    lines += ["", *_ask_lines(brief)]
    lines += ["", *_shelved_lines(brief)]
    return "\n".join(lines) + "\n"


__all__ = [
    "QUESTION_CHARS",
    "QUESTION_MARKER",
    "SHELVED_LISTED",
    "ActivityReader",
    "KnownIssue",
    "Shelved",
    "ShelvedRead",
    "ShelvedReader",
    "ThreadReader",
    "UrgentRead",
    "UrgentReader",
    "SHIPPED_PER_REPO",
    "Brief",
    "compose",
    "known_failures",
    "liveness_urgent",
    "question_text",
    "render",
]
