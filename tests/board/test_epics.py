# ABOUTME: Tests for the epic-health model — how the board decides an epic has gone quiet,
# ABOUTME: lost its parent, finished without closing, or never had children.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from oversteward.board.epics import (
    QUIET_AFTER_DAYS,
    STALLED_AFTER_DAYS,
    EpicHealth,
    build_epics,
)
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
    return Issue.from_gh(
        repo,
        {
            "number": number,
            "title": title,
            "url": f"https://github.com/NathanKrupa/{repo}/issues/{number}",
            "state": state,
            "labels": [{"name": name} for name in labels],
            "createdAt": (NOW - timedelta(days=90)).isoformat(),
            "updatedAt": updated.isoformat(),
            "closedAt": None if closed is None else closed.isoformat(),
            "body": body,
        },
    )


def test_children_come_from_the_slug_label_and_the_parent_body_mentions():
    parent = issue(1, "Epic: verification spine", labels=("epic:spine",), body="- [ ] #2\n- [x] #4")
    by_label = issue(2, labels=("epic:spine",))
    by_body = issue(4, state="CLOSED", closed_days_ago=1)
    unrelated = issue(3)

    (epic,) = build_epics((parent, by_label, by_body, unrelated))

    assert epic.key == "epic:spine"
    assert epic.parent is parent
    assert {c.number for c in epic.children} == {2, 4}


def test_a_child_carrying_the_label_is_counted_once_even_when_the_body_mentions_it():
    parent = issue(1, "Epic: x", labels=("epic:x",), body="#2")
    child = issue(2, labels=("epic:x",))

    (epic,) = build_epics((parent, child))

    assert len(epic.children) == 1


def test_a_label_with_children_but_no_epic_issue_is_label_only():
    child = issue(2, labels=("epic:crawler-resilience",))

    (epic,) = build_epics((child,))

    assert epic.parent is None
    assert epic.health(NOW) is EpicHealth.LABEL_ONLY


def test_an_epic_whose_parent_closed_with_open_children_is_parent_closed():
    parent = issue(1, "Epic: x", labels=("epic:x",), state="CLOSED", closed_days_ago=3)
    child = issue(2, labels=("epic:x",))

    (epic,) = build_epics((parent, child))

    assert epic.health(NOW) is EpicHealth.PARENT_CLOSED


def test_a_closed_parent_whose_children_are_all_closed_is_not_an_epic_on_the_board():
    parent = issue(1, "Epic: x", labels=("epic:x",), state="CLOSED", closed_days_ago=3)
    child = issue(2, labels=("epic:x",), state="CLOSED", closed_days_ago=5)

    assert build_epics((parent, child)) == ()


def test_an_open_parent_with_no_children_is_childless():
    parent = issue(1, "epic(gov): parity", labels=("epic:gov",))

    (epic,) = build_epics((parent,))

    assert epic.health(NOW) is EpicHealth.CHILDLESS


def test_an_epic_titled_issue_without_a_slug_label_is_keyed_by_its_number():
    parent = issue(7, "epic(gov): parity", body="#8")
    child = issue(8)

    (epic,) = build_epics((parent, child))

    assert epic.key == "#7"
    assert [c.number for c in epic.children] == [8]


def test_an_open_parent_whose_children_are_all_closed_is_done_but_open():
    parent = issue(1, "Epic: x", labels=("epic:x",))
    child = issue(2, labels=("epic:x",), state="CLOSED", closed_days_ago=2)

    (epic,) = build_epics((parent, child))

    assert epic.health(NOW) is EpicHealth.DONE_OPEN


@pytest.mark.parametrize(
    ("days_quiet", "expected"),
    [
        (0, EpicHealth.ACTIVE),
        (QUIET_AFTER_DAYS - 1, EpicHealth.ACTIVE),
        (QUIET_AFTER_DAYS, EpicHealth.QUIET),
        (STALLED_AFTER_DAYS - 1, EpicHealth.QUIET),
        (STALLED_AFTER_DAYS, EpicHealth.STALLED),
    ],
)
def test_quiet_and_stalled_are_measured_from_the_last_child_motion(days_quiet, expected):
    parent = issue(1, "Epic: x", labels=("epic:x",), updated_days_ago=0)
    child = issue(2, labels=("epic:x",), updated_days_ago=days_quiet)

    (epic,) = build_epics((parent, child))

    assert epic.days_quiet(NOW) == days_quiet
    assert epic.health(NOW) is expected


def test_parent_motion_does_not_count_as_epic_motion():
    """A parent edited yesterday while every child sat for 40 days is still stalled —
    the parent's updatedAt moves on every label tweak and comment."""
    parent = issue(1, "Epic: x", labels=("epic:x",), updated_days_ago=1)
    child = issue(2, labels=("epic:x",), updated_days_ago=40)

    (epic,) = build_epics((parent, child))

    assert epic.health(NOW) is EpicHealth.STALLED


def test_last_motion_was_a_close_when_the_freshest_child_event_is_a_close():
    parent = issue(1, "Epic: x", labels=("epic:x",))
    still_open = issue(2, labels=("epic:x",), updated_days_ago=10)
    just_closed = issue(3, labels=("epic:x",), state="CLOSED", closed_days_ago=2, updated_days_ago=2)

    (epic,) = build_epics((parent, still_open, just_closed))

    assert epic.last_motion_was_close is True
    assert epic.open_children == 1
    assert epic.closed_children == 1


def test_last_motion_was_not_a_close_when_an_open_child_moved_more_recently():
    parent = issue(1, "Epic: x", labels=("epic:x",))
    still_open = issue(2, labels=("epic:x",), updated_days_ago=1)
    closed_earlier = issue(3, labels=("epic:x",), state="CLOSED", closed_days_ago=2, updated_days_ago=2)

    (epic,) = build_epics((parent, still_open, closed_earlier))

    assert epic.last_motion_was_close is False


def test_epics_are_scoped_per_repo_so_shared_slugs_do_not_merge():
    gs = issue(1, "Epic: google first", labels=("epic:google-first",), repo="grantspider")
    ag = issue(1, "Epic: google first", labels=("epic:google-first",), repo="aigranthelper")

    epics = build_epics((gs, ag))

    assert sorted((e.repo, e.key) for e in epics) == [
        ("aigranthelper", "epic:google-first"),
        ("grantspider", "epic:google-first"),
    ]


def test_body_mentions_only_resolve_within_the_same_repo():
    parent = issue(1, "Epic: x", body="#2", repo="grantspider")
    other_repo = issue(2, repo="aigranthelper")

    (epic,) = build_epics((parent, other_repo))

    assert epic.children == ()


def test_an_open_parent_outranks_a_closed_one_carrying_the_same_slug():
    """A slug reused across a retired epic and its successor belongs to the open one."""
    retired = issue(1, "Epic: x (v1)", labels=("epic:x",), state="CLOSED", closed_days_ago=60)
    successor = issue(5, "Epic: x (v2)", labels=("epic:x",))
    child = issue(2, labels=("epic:x",))

    (epic,) = build_epics((retired, child, successor))

    assert epic.parent is successor
    assert epic.health(NOW) is EpicHealth.ACTIVE


def test_a_comment_on_a_closed_child_is_not_motion():
    """GitHub bumps updatedAt when someone comments on a closed issue; the close is the event."""
    parent = issue(1, "Epic: x", labels=("epic:x",))
    still_open = issue(2, labels=("epic:x",), updated_days_ago=3)
    closed_then_discussed = issue(
        3, labels=("epic:x",), state="CLOSED", closed_days_ago=5, updated_days_ago=1
    )

    (epic,) = build_epics((parent, still_open, closed_then_discussed))

    assert epic.last_motion_was_close is False
    assert epic.days_quiet(NOW) == 3
