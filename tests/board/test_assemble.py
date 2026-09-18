# ABOUTME: Tests for the board assembly — what wants Nathan's decision, and the counts beside it.
# ABOUTME: Decisions come only from needs-input issues and epics whose health asks for one.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from oversteward.board.assemble import STALE_ANSWER_HOURS, DecisionKind, assemble
from oversteward.board.epics import STALLED_AFTER_DAYS
from oversteward.board.models import Issue

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def issue(
    number: int,
    title: str = "a task",
    *,
    labels: tuple[str, ...] = (),
    state: str = "OPEN",
    updated_days_ago: float = 0,
    closed_days_ago: float | None = None,
    body: str = "",
    repo: str = "grantspider",
) -> Issue:
    updated = NOW - timedelta(days=updated_days_ago)
    closed = None if closed_days_ago is None else NOW - timedelta(days=closed_days_ago)
    return Issue.from_gh(repo, {
        "number": number, "title": title, "state": state, "body": body,
        "url": f"https://github.com/NathanKrupa/{repo}/issues/{number}",
        "labels": [{"name": name} for name in labels],
        "createdAt": (NOW - timedelta(days=90)).isoformat(),
        "updatedAt": updated.isoformat(),
        "closedAt": None if closed is None else closed.isoformat(),
    })


def test_counts_per_repo_follow_the_label_vocabulary():
    issues = {
        "grantspider": (
            issue(1, labels=("needs-input",), updated_days_ago=3),
            issue(2, labels=("ready-for-agent",)),
            issue(3, labels=("agent-in-progress",)),
            issue(4, labels=("needs-scoping",)),
            issue(5, labels=("needs-scoping", "bug")),
            issue(6),                                  # untriaged, but not yet asked for scoping
            issue(7, "Epic: x", labels=("epic:x",)),   # a container, not a scoping candidate
            issue(8, state="CLOSED", closed_days_ago=1, labels=("epic:x",)),
        ),
    }

    report = assemble(issues, now=NOW)

    (gs,) = report.repos
    assert gs.repo == "grantspider"
    assert gs.open == 7
    assert gs.needs_input == 1
    assert gs.ready == 1
    assert gs.in_progress == 1
    assert gs.needs_scoping == 2
    assert gs.epics == 1


def test_a_needs_input_issue_is_a_decision_aged_from_its_last_update():
    issues = {"grantspider": (issue(1, "which schema?", labels=("needs-input",), updated_days_ago=3),)}

    report = assemble(issues, now=NOW)

    (decision,) = report.decisions
    assert decision.kind is DecisionKind.ANSWER
    assert decision.repo == "grantspider"
    assert decision.ref == "#1"
    assert decision.title == "which schema?"
    assert decision.url.endswith("/issues/1")
    assert decision.age_days == 3
    assert decision.stale is True


def test_a_fresh_question_is_not_stale():
    fresh_hours = STALE_ANSWER_HOURS - 1
    issues = {"grantspider": (
        issue(1, labels=("needs-input",), updated_days_ago=fresh_hours / 24),
    )}

    (decision,) = assemble(issues, now=NOW).decisions

    assert decision.stale is False


def test_an_epic_wanting_a_decision_is_a_decision_and_a_healthy_one_is_not():
    issues = {"grantspider": (
        issue(1, "Epic: alive", labels=("epic:alive",)),
        issue(2, labels=("epic:alive",), updated_days_ago=1),
        issue(3, "Epic: dropped", labels=("epic:dropped",)),
        issue(4, labels=("epic:dropped",), updated_days_ago=STALLED_AFTER_DAYS + 5),
        issue(5, labels=("epic:orphan",)),
    )}

    report = assemble(issues, now=NOW)

    by_ref = {d.ref: d for d in report.decisions}
    assert set(by_ref) == {"epic:dropped", "epic:orphan"}
    assert by_ref["epic:dropped"].kind is DecisionKind.EPIC
    assert by_ref["epic:dropped"].age_days == STALLED_AFTER_DAYS + 5
    assert str(STALLED_AFTER_DAYS + 5) in by_ref["epic:dropped"].ask
    assert by_ref["epic:dropped"].url.endswith("/issues/3")
    assert by_ref["epic:orphan"].url.endswith("label%3A%22epic%3Aorphan%22")
    assert "epic:orphan" in by_ref["epic:orphan"].ask
    assert len(report.epics) == 3


def test_questions_come_first_oldest_first_then_epics():
    issues = {
        "aigranthelper": (
            issue(1, labels=("needs-input",), updated_days_ago=1, repo="aigranthelper"),
            issue(2, "Epic: x", labels=("epic:x",), repo="aigranthelper"),
        ),
        "grantspider": (
            issue(9, labels=("needs-input",), updated_days_ago=20),
        ),
    }

    report = assemble(issues, now=NOW)

    assert [(d.repo, d.ref) for d in report.decisions] == [
        ("grantspider", "#9"),
        ("aigranthelper", "#1"),
        ("aigranthelper", "epic:x"),
    ]


def test_repos_keep_the_order_they_were_given():
    issues = {"wphelper": (), "aigranthelper": (issue(1, repo="aigranthelper"),)}

    report = assemble(issues, now=NOW)

    assert [r.repo for r in report.repos] == ["wphelper", "aigranthelper"]
    assert report.repos[0].open == 0


def test_a_question_exactly_at_the_stale_boundary_is_stale():
    issues = {"grantspider": (
        issue(1, labels=("needs-input",), updated_days_ago=STALE_ANSWER_HOURS / 24),
    )}

    (decision,) = assemble(issues, now=NOW).decisions

    assert decision.stale is True


def test_a_closed_issue_still_wearing_needs_input_is_not_a_decision():
    """The client fetches closed epic children; one closed with the label left on is history."""
    issues = {"grantspider": (
        issue(1, "Epic: x", labels=("epic:x",)),
        issue(2, labels=("epic:x",), updated_days_ago=1),
        issue(3, labels=("epic:x", "needs-input"), state="CLOSED", closed_days_ago=2),
    )}

    report = assemble(issues, now=NOW)

    assert report.decisions == ()
    assert report.repos[0].needs_input == 0
