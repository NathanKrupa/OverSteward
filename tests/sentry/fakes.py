# ABOUTME: Fake Sentry connector, shared literals, and an issue builder for the triage tests.
# ABOUTME: No network, no token, no environment reads — the seam is the IssueSource protocol.

from __future__ import annotations

from collections.abc import Sequence

from oversteward.sentry.client import SentryUnavailableError
from oversteward.sentry.models import SentryIssue, SentryProject

TOKEN = "sntrys-not-a-real-token"

#: The org's two current project slugs. GS#2187 renames `python` to
#: `grantspider`; nothing here or in the tool hardcodes them as a pair.
AG = "aigranthelper"
GS = "python"

AG_1 = "AIGRANTHELPER-1"
AG_2 = "AIGRANTHELPER-2"
GS_9 = "PYTHON-9"

FIRST_SEEN = "2026-08-01T00:00:00Z"
AUTH_FAILURE = "Sentry returned HTTP 401"


def issue(short_id: str, project: str = AG, **overrides) -> SentryIssue:
    """One issue with plausible defaults; override any field by keyword."""
    fields = {
        "id": short_id.lower().replace("-", ""),
        "short_id": short_id,
        "project": project,
        "title": f"{short_id} blew up",
        "first_seen": FIRST_SEEN,
        "permalink": f"https://sentry.io/x/{short_id}/",
        "count": 3,
    }
    fields.update(overrides)
    return SentryIssue(**fields)


def two_project_sentry() -> FakeSentry:
    """The shape of a real sweep: two projects, three unresolved issues."""
    return FakeSentry({AG: [issue(AG_1), issue(AG_2)], GS: [issue(GS_9, project=GS)]})


def one_issue_sentry() -> FakeSentry:
    """A single project with a single unresolved issue — the smallest real queue."""
    return FakeSentry({AG: [issue(AG_1)]})


def empty_sentry() -> FakeSentry:
    """A reachable Sentry with nothing unresolved."""
    return FakeSentry({AG: []})


def blind_sentry() -> FakeSentry:
    """A Sentry that cannot be read — the "could not look" case."""
    return FakeSentry({AG: []}, fail_with=AUTH_FAILURE)


class FakeSentry:
    """An in-memory stand-in for SentryClient, recording what was asked of it."""

    def __init__(
        self,
        issues_by_project: dict[str, list[SentryIssue]] | None = None,
        *,
        fail_with: str = "",
    ) -> None:
        self._issues = issues_by_project or {}
        self._fail_with = fail_with
        self.resolved: list[tuple[str, str]] = []

    def list_projects(self) -> Sequence[SentryProject]:
        self._check()
        return [SentryProject(slug=slug, name=slug) for slug in sorted(self._issues)]

    def list_unresolved_issues(self, project_slug: str) -> Sequence[SentryIssue]:
        self._check()
        return list(self._issues.get(project_slug, []))

    def resolve_issue(self, issue_id: str, *, comment: str = "") -> None:
        self._check()
        self.resolved.append((issue_id, comment))

    def _check(self) -> None:
        if self._fail_with:
            raise SentryUnavailableError(self._fail_with)
