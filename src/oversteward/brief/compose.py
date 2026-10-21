# ABOUTME: MIDDLE service for the Estate Brief — decides what shipped, the one ask, and what is URGENT.
# ABOUTME: Renders a short plain-markdown note a vault-only skill reads aloud; it never writes a file.

"""Compose the nightly Estate Brief.

The brief is read aloud at the morning check-in by a skill that can only read
vault files, so it says four things and nothing else:

* **URGENT** — a Railway service that is down, or a liveness sweep that could
  not look. Rendered only when there is something to say.
* **Shipped** — pull requests *merged* in the window, grouped by repository,
  with a count. A pull request closed without merging never counts, and
  ``0 shipped`` is a measured answer, not a missing one.
* **The one ask** — at most one ``needs-input`` issue: the oldest open one.
  Every other ask stays out of the note by design.
* **Shelved overnight** — a placeholder until the shelving sweep (#612) lands.

GitHub failures propagate: a brief missing a repository is a smaller estate
than exists. A liveness sweep that could not look does not stop the brief —
the note still ships, with the blind source named under URGENT — but the
brief records it, so the caller can exit non-zero.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from oversteward.board.client import read_estate
from oversteward.board.config import RepoRef
from oversteward.board.models import Issue
from oversteward.brief.client import PullRequest, RepoActivity, read_activity
from oversteward.liveness.check import ProjectRef, sweep
from oversteward.liveness.client import RailwayConfigError, RailwayUnavailableError
from oversteward.liveness.models import LivenessReport

#: Merged pull requests listed per repository before the rest collapse to ``+N more``.
SHIPPED_PER_REPO = 3

SHELVED_PLACEHOLDER = "not yet wired (#612)"

ActivityReader = Callable[[RepoRef, datetime], RepoActivity]
UrgentReader = Callable[[], Sequence[str]]


@dataclass(frozen=True, slots=True)
class Brief:
    generated_at: datetime
    window: timedelta
    #: ``(repo id, merged pull requests)`` for each repository that shipped, in registry order.
    shipped: tuple[tuple[str, tuple[PullRequest, ...]], ...]
    ask: Issue | None
    urgent: tuple[str, ...]
    #: True when an URGENT source could not be read; the note says so under URGENT.
    urgent_blind: bool

    @property
    def shipped_count(self) -> int:
        return sum(len(pulls) for _, pulls in self.shipped)


def liveness_urgent(
    projects: Sequence[ProjectRef],
    *,
    sweeper: Callable[[Sequence[ProjectRef]], LivenessReport] = sweep,
) -> tuple[str, ...]:
    """One line per Railway service that is down or in a state nothing classifies."""
    report = sweeper(projects)
    return tuple(
        f"Railway: {state.project} / {state.name} is {state.status or 'in an unknown state'}"
        for state in report.findings
    )


def _merged_in_window(pulls: Sequence[PullRequest], since: datetime) -> tuple[PullRequest, ...]:
    shipped = [p for p in pulls if p.merged_at is not None and p.merged_at >= since]
    return tuple(sorted(shipped, key=lambda p: p.merged_at))


def _oldest_ask(activity: Sequence[RepoActivity]) -> Issue | None:
    asks = [issue for repo in activity for issue in repo.asks if issue.is_open]
    if not asks:
        return None
    return min(asks, key=lambda issue: (issue.created_at, issue.repo, issue.number))


def _read_urgent(read_urgent: UrgentReader) -> tuple[tuple[str, ...], bool]:
    try:
        return tuple(read_urgent()), False
    except (RailwayUnavailableError, RailwayConfigError) as exc:
        return (f"Could not check Railway — {exc}",), True


def compose(
    repos: Sequence[RepoRef],
    *,
    now: datetime,
    window: timedelta,
    read_urgent: UrgentReader,
    read: ActivityReader = read_activity,
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
    urgent, blind = _read_urgent(read_urgent)
    return Brief(
        generated_at=now,
        window=window,
        shipped=shipped,
        ask=_oldest_ask(activity),
        urgent=urgent,
        urgent_blind=blind,
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
    lines += ["", "## The one ask", ""]
    if brief.ask is None:
        lines.append("Nothing is waiting on you.")
    else:
        ask = brief.ask
        lines.append(f"[{ask.title}]({ask.url}) — {ask.repo} #{ask.number}")
    lines += ["", "## Shelved overnight", "", SHELVED_PLACEHOLDER]
    return "\n".join(lines) + "\n"


__all__ = [
    "SHELVED_PLACEHOLDER",
    "ActivityReader",
    "UrgentReader",
    "SHIPPED_PER_REPO",
    "Brief",
    "compose",
    "liveness_urgent",
    "render",
]
