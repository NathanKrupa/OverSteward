# ABOUTME: One open GitHub issue as intake reads it — labels, title, body and age.
# ABOUTME: Built from a `gh issue list --json` row; the services below never touch gh themselves.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntakeIssue:
    """An open issue in one repository, keyed by the registry id of that repository."""

    repo: str
    number: int
    title: str
    labels: frozenset[str]
    body: str
    #: ISO-8601 as gh prints it (``2026-10-21T12:00:00Z``); sorts lexically by time.
    created_at: str
    url: str

    @classmethod
    def from_gh(cls, repo: str, raw: dict) -> IntakeIssue:
        return cls(
            repo=repo,
            number=int(raw["number"]),
            title=raw.get("title") or "",
            labels=frozenset(label["name"] for label in raw.get("labels") or ()),
            body=raw.get("body") or "",
            created_at=raw.get("createdAt") or "",
            url=raw.get("url") or "",
        )
