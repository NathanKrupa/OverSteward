# ABOUTME: Tests for the tribe-first dispatch queue and the displaced-tribe notice.
# ABOUTME: Nathan 2026-10-21: tribe outranks every other issue, a paying client's included.

from __future__ import annotations

from oversteward.intake.queue import (
    dispatch_queue,
    displaced_by,
    rank,
    render_displacement,
)

from .conftest import issue


def test_rank_puts_a_younger_tribe_issue_ahead_of_an_older_plain_one():
    old_plain = issue(1, created="2026-01-01T00:00:00Z")
    young_tribe = issue(2, labels=("tribe",), created="2026-10-01T00:00:00Z")
    assert [i.number for i in rank([old_plain, young_tribe])] == [2, 1]


def test_rank_is_oldest_first_within_a_class():
    a = issue(5, created="2026-03-01T00:00:00Z")
    b = issue(3, created="2026-02-01T00:00:00Z")
    t1 = issue(9, labels=("tribe",), created="2026-05-01T00:00:00Z")
    t2 = issue(8, labels=("tribe",), created="2026-04-01T00:00:00Z")
    assert [i.number for i in rank([a, t1, b, t2])] == [8, 9, 3, 5]


def test_rank_breaks_a_created_at_tie_by_number():
    same = "2026-03-01T00:00:00Z"
    assert [i.number for i in rank([issue(7, created=same), issue(4, created=same)])] == [4, 7]


def test_dispatch_queue_holds_only_ready_issues():
    ready = issue(1, labels=("ready-for-agent",))
    unready_tribe = issue(2, labels=("tribe",))
    assert [i.number for i in dispatch_queue([ready, unready_tribe])] == [1]


def test_dispatch_queue_drops_each_blocking_label():
    blocked = [
        issue(n, labels=("ready-for-agent", "tribe", label))
        for n, label in enumerate(
            ("agent-in-progress", "needs-input", "needs-scoping", "reject-close", "shelved"),
            start=10,
        )
    ]
    assert dispatch_queue(blocked) == ()


def test_dispatch_queue_ranks_tribe_first():
    plain = issue(1, labels=("ready-for-agent",), created="2026-01-01T00:00:00Z")
    tribe = issue(2, labels=("ready-for-agent", "tribe"), created="2026-09-01T00:00:00Z")
    assert [i.number for i in dispatch_queue([plain, tribe])] == [2, 1]


def test_a_plain_dispatch_displaces_every_ready_tribe_issue():
    target = issue(1, labels=("ready-for-agent",))
    t1 = issue(2, labels=("ready-for-agent", "tribe"))
    t2 = issue(3, labels=("ready-for-agent", "tribe"))
    assert [i.number for i in displaced_by(target, [target, t1, t2])] == [2, 3]


def test_a_tribe_dispatch_displaces_nothing():
    target = issue(1, labels=("ready-for-agent", "tribe"))
    other = issue(2, labels=("ready-for-agent", "tribe"))
    assert displaced_by(target, [target, other]) == ()


def test_an_unready_tribe_issue_is_not_displaced():
    target = issue(1, labels=("ready-for-agent",))
    scoping = issue(2, labels=("tribe", "needs-scoping"))
    unlabelled = issue(3, labels=("tribe",))
    assert displaced_by(target, [target, scoping, unlabelled]) == ()


def test_a_tribe_issue_already_in_flight_is_not_displaced():
    target = issue(1, labels=("ready-for-agent",))
    in_flight = issue(2, labels=("ready-for-agent", "tribe", "agent-in-progress"))
    assert displaced_by(target, [target, in_flight]) == ()


def test_the_notice_names_each_displaced_issue():
    target = issue(1, title="refactor the settings page", labels=("ready-for-agent",))
    displaced = (issue(42, title="Pantry user cannot save a draft", labels=("tribe",)),)
    notice = render_displacement("aigranthelper", target, displaced)
    assert "aigranthelper#1" in notice
    assert "#42" in notice
    assert "Pantry user cannot save a draft" in notice
    assert displaced[0].url in notice


def test_no_displacement_renders_a_measured_line_not_silence():
    target = issue(1, labels=("ready-for-agent",))
    notice = render_displacement("aigranthelper", target, ())
    assert "0 ready tribe issues displaced" in notice
