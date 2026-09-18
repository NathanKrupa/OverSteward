# ABOUTME: Tests for the board's HTML — the numbers and decisions land on the page,
# ABOUTME: untrusted issue titles are escaped, and an empty queue says so plainly.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oversteward.board.assemble import assemble
from oversteward.board.models import Issue
from oversteward.board.render import render

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def issue(
    number,
    title="a task",
    *,
    labels=(),
    state="OPEN",
    updated_days_ago=0,
    closed_days_ago=None,
    body="",
    repo="grantspider",
) -> Issue:
    updated = NOW - timedelta(days=updated_days_ago)
    closed = None if closed_days_ago is None else NOW - timedelta(days=closed_days_ago)
    return Issue.from_gh(
        repo,
        {
            "number": number,
            "title": title,
            "state": state,
            "body": body,
            "url": f"https://github.com/NathanKrupa/{repo}/issues/{number}",
            "labels": [{"name": n} for n in labels],
            "createdAt": (NOW - timedelta(days=90)).isoformat(),
            "updatedAt": updated.isoformat(),
            "closedAt": None if closed is None else closed.isoformat(),
        },
    )


def report_with_decisions():
    return assemble(
        {
            "grantspider": (
                issue(1, "which <b>schema</b>?", labels=("needs-input",), updated_days_ago=3),
                issue(2, "Epic: dropped", labels=("epic:dropped",)),
                issue(3, labels=("epic:dropped",), updated_days_ago=45),
                issue(4, labels=("ready-for-agent",)),
            ),
            "aigranthelper": (
                issue(7, "Epic: alive", labels=("epic:alive",), repo="aigranthelper"),
                issue(8, labels=("epic:alive",), updated_days_ago=1, repo="aigranthelper"),
            ),
        },
        now=NOW,
    )


def test_the_page_carries_the_stamp_the_decisions_and_the_counts():
    html = render(report_with_decisions())

    assert "<title>Estate Board</title>" in html
    assert "2026-09-18" in html and "12:00 UTC" in html
    assert "https://github.com/NathanKrupa/grantspider/issues/1" in html
    assert "Answer the agent" in html
    assert "epic:dropped" in html
    assert "45 days" in html
    # counts row for grantspider: 4 open, 1 needs-input, 1 ready
    assert "grantspider" in html and ">4<" in html


def test_issue_titles_are_escaped_not_rendered():
    html = render(report_with_decisions())

    assert "<b>schema</b>" not in html
    assert "&lt;b&gt;schema&lt;/b&gt;" in html


def test_a_healthy_epic_appears_in_the_health_table_but_not_the_queue():
    html = render(report_with_decisions())

    queue = html[html.index('id="decisions"') : html.index('id="epics"')]
    assert "epic:alive" not in queue
    assert "epic:alive" in html[html.index('id="epics"') :]


def test_an_empty_queue_says_nothing_waits():
    report = assemble({"grantspider": (issue(1, labels=("ready-for-agent",)),)}, now=NOW)

    html = render(report)

    assert "Nothing waits on you" in html


def test_the_page_names_what_it_cannot_yet_do():
    html = render(report_with_decisions())

    assert "GitHub connector" in html
