# ABOUTME: MIDDLE service for Sentry triage — the verdict ledger, the sweep diff, and the record step.
# ABOUTME: Steady state is inbox zero on Sentry *issues*: every one fixed, filed, or resolved-with-reason.

"""Deterministic Sentry triage (OS#338).

Sentry-native email alerts are Layer 0 — they tell you something happened. This
module is the pull side: it answers *what has not been ruled on yet*, and
remembers every ruling so the answer drains instead of repeating.

**Why a verdict ledger.** "Unresolved in Sentry" is not the same question as
"unread by us". An issue that has been filed as a repo issue is still unresolved
in Sentry — correctly so, since the bug is still there — but it is no longer
untriaged. Subtracting recorded verdicts is what turns a permanently-red list
into a queue that reaches zero, and what makes a future cron backstop (OS#339)
a safe no-op rather than a nightly re-notification.

**Why "nothing new" and "could not look" must differ.** A sweep that could not
reach Sentry has found nothing *and knows nothing*. Rendering it like a clean
sweep converts an outage into a false all-clear — the same doctrine the
worktree doctor's ``sweep`` verb follows. The service raises
:class:`~oversteward.sentry.client.SentryUnavailableError` rather than returning
an empty result, so the two can never share an exit path.

There are no LLM calls here, by design: this decides what is *unread*, never
what the fix should be.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import SentryIssue, SentryProject

#: The three ways an issue leaves the queue. All are terminal — there is no
#: "later", because "later" is how an inbox stops being zero.
VERDICTS: tuple[str, ...] = ("fixed", "filed", "noise-resolved")

#: On-disk keys, shared by the ledger and the pending snapshot. Sentry's own
#: camelCase spelling is kept so a line reads the same as the API response it
#: came from.
KEY_SHORT_ID = "shortId"
KEY_ID = "id"
KEY_PROJECT = "project"
KEY_TITLE = "title"
KEY_FIRST_SEEN = "firstSeen"


class TriageError(RuntimeError):
    """Raised when a verdict cannot be recorded as asked."""


class IssueSource(Protocol):
    """The slice of the Sentry connector the sweep depends on."""

    def list_projects(self) -> Sequence[SentryProject]: ...

    def list_unresolved_issues(self, project_slug: str) -> Sequence[SentryIssue]: ...


@dataclass(frozen=True)
class LedgerEntry:
    """One recorded ruling. Keyed by ``short_id``; a later line supersedes an earlier one."""

    short_id: str
    issue_id: str
    project: str
    title: str
    first_seen: str
    verdict: str
    ref: str
    recorded_at: str

    def to_dict(self) -> dict:
        return {
            KEY_SHORT_ID: self.short_id,
            KEY_ID: self.issue_id,
            KEY_PROJECT: self.project,
            KEY_TITLE: self.title,
            KEY_FIRST_SEEN: self.first_seen,
            "verdict": self.verdict,
            "ref": self.ref,
            "recordedAt": self.recorded_at,
        }


@dataclass(frozen=True)
class SweepResult:
    """What one sweep saw. ``new_issues`` is the queue; the counts are the context."""

    projects: tuple[str, ...]
    new_issues: tuple[SentryIssue, ...]
    unresolved_count: int
    recorded_count: int

    @property
    def is_current(self) -> bool:
        return not self.new_issues


@dataclass(frozen=True)
class TriageStore:
    """The two files triage keeps: the durable ledger, and the last sweep's queue.

    The pending snapshot exists so ``record`` needs no network. An issue ruled
    ``fixed`` is resolved in Sentry first, which removes it from the unresolved
    list — so re-fetching its metadata at record time would fail exactly when it
    matters most.
    """

    ledger_path: Path
    pending_path: Path

    def recorded(self) -> dict[str, LedgerEntry]:
        """Every ruling so far, keyed by short id. A damaged line is skipped, not fatal."""
        entries: dict[str, LedgerEntry] = {}
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except OSError:
            return entries
        for line in text.splitlines():
            entry = _entry_from_line(line)
            if entry is not None:
                entries[entry.short_id] = entry
        return entries

    def append(self, entry: LedgerEntry) -> None:
        """Append one ruling. The ledger is append-only; the last line for a key wins."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")

    def pending(self) -> dict[str, SentryIssue]:
        """The last sweep's untriaged issues, keyed by short id."""
        try:
            rows = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(rows, list):
            return {}
        issues = [_issue_from_row(row) for row in rows]
        return {issue.short_id: issue for issue in issues if issue.short_id}

    def save_pending(self, issues: Iterable[SentryIssue]) -> None:
        """Replace the pending snapshot. Only ever called after a sweep that succeeded."""
        rows = [_row_for_issue(issue) for issue in issues]
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")


def _row_for_issue(issue: SentryIssue) -> dict:
    return {
        KEY_ID: issue.id,
        KEY_SHORT_ID: issue.short_id,
        KEY_PROJECT: issue.project,
        KEY_TITLE: issue.title,
        KEY_FIRST_SEEN: issue.first_seen,
        "permalink": issue.permalink,
        "count": issue.count,
    }


def _issue_from_row(row: dict) -> SentryIssue:
    return SentryIssue(
        id=str(row.get(KEY_ID, "")),
        short_id=str(row.get(KEY_SHORT_ID, "")),
        project=str(row.get(KEY_PROJECT, "")),
        title=str(row.get(KEY_TITLE, "")),
        first_seen=str(row.get(KEY_FIRST_SEEN, "")),
        permalink=str(row.get("permalink", "")),
        count=int(row.get("count") or 0),
    )


def _entry_from_line(line: str) -> LedgerEntry | None:
    """One ledger line, or None if it is blank or damaged."""
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get(KEY_SHORT_ID):
        return None
    return LedgerEntry(
        short_id=str(payload.get(KEY_SHORT_ID, "")),
        issue_id=str(payload.get(KEY_ID, "")),
        project=str(payload.get(KEY_PROJECT, "")),
        title=str(payload.get(KEY_TITLE, "")),
        first_seen=str(payload.get(KEY_FIRST_SEEN, "")),
        verdict=str(payload.get("verdict", "")),
        ref=str(payload.get("ref", "")),
        recorded_at=str(payload.get("recordedAt", "")),
    )


def sweep(source: IssueSource, store: TriageStore) -> SweepResult:
    """Unresolved issues across every project, minus the ones already ruled on.

    Raises rather than returning an empty result when Sentry cannot be reached —
    see the module docstring on why the two outcomes must never converge.
    """
    ruled = store.recorded()
    projects = list(source.list_projects())
    issues: list[SentryIssue] = []
    for project in projects:
        issues.extend(source.list_unresolved_issues(project.slug))
    new = tuple(issue for issue in issues if issue.short_id not in ruled)
    return SweepResult(
        projects=tuple(project.slug for project in projects),
        new_issues=new,
        unresolved_count=len(issues),
        recorded_count=len(ruled),
    )


def record(
    store: TriageStore,
    short_id: str,
    verdict: str,
    ref: str,
    when: datetime,
) -> LedgerEntry:
    """Rule on one issue, so the next sweep no longer offers it.

    The issue's metadata comes from the pending snapshot rather than a fresh
    fetch, so a verdict can still be recorded after the issue was resolved in
    Sentry. The clock is a parameter: nothing here reads it.
    """
    if verdict not in VERDICTS:
        raise TriageError(f"unknown verdict {verdict!r} — expected one of {', '.join(VERDICTS)}")
    issue = store.pending().get(short_id)
    if issue is None:
        raise TriageError(
            f"{short_id} is not in the last sweep's queue — run `sentry_triage.py sweep` first, "
            "or check the short id."
        )
    entry = _ruling(issue, verdict, ref, when)
    store.append(entry)
    return entry


def _ruling(issue: SentryIssue, verdict: str, ref: str, when: datetime) -> LedgerEntry:
    """The ledger line for one ruling — the issue's identity plus the verdict."""
    return LedgerEntry(
        short_id=issue.short_id,
        issue_id=issue.id,
        project=issue.project,
        title=issue.title,
        first_seen=issue.first_seen,
        verdict=verdict,
        ref=ref,
        recorded_at=when.isoformat(),
    )
