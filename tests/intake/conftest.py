# ABOUTME: Shared fixture builder for intake tests — one gh-shaped issue row at a time.
# ABOUTME: Rows mirror `gh issue list --json number,title,labels,body,createdAt,url`.

from __future__ import annotations

from oversteward.intake.models import IntakeIssue


def gh_row(
    number: int,
    *,
    title: str = "an issue",
    labels: tuple[str, ...] = (),
    body: str = "",
    created: str = "2026-10-01T00:00:00Z",
    repo_slug: str = "NathanKrupa/aigranthelper",
) -> dict:
    return {
        "number": number,
        "title": title,
        "labels": [{"name": name} for name in labels],
        "body": body,
        "createdAt": created,
        "url": f"https://github.com/{repo_slug}/issues/{number}",
    }


def issue(number: int, *, repo: str = "aigranthelper", **kwargs) -> IntakeIssue:
    return IntakeIssue.from_gh(repo, gh_row(number, **kwargs))
