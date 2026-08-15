# ABOUTME: Tests for the session-start kaizen queue (OS#332) — verdicts, merge, ranking, next item.
# ABOUTME: All against injected inputs; nothing here touches the live ledger or GitHub.

from __future__ import annotations

from datetime import date

import pytest

from oversteward.dream.kaizen import (
    KaizenItem,
    build_queue,
    candidate_key,
    format_next,
    issue_key,
    next_item,
    read_verdicts,
    record_verdict,
)
from oversteward.dream.promotion import FalseGreenError, PromotionCandidate


def _candidate(text: str, count: int, target: str = "doctrine") -> PromotionCandidate:
    return PromotionCandidate(
        canonical_text=text,
        category="tooling",
        count=count,
        repos=["oversteward"],
        target=target,
        section="candidate_lessons",
        prs=["oversteward#100"],
    )


def _issue(number: int, title: str, labels=("kaizen",)) -> dict:
    return {"number": number, "title": title, "labels": [{"name": n} for n in labels]}


# --- stable keys ------------------------------------------------------------


def test_candidate_key_is_stable_across_identical_text() -> None:
    a = _candidate("provision the venv before first use", 9)
    b = _candidate("provision the venv before first use", 14)

    assert candidate_key(a) == candidate_key(b)


def test_candidate_key_ignores_case_and_punctuation_drift() -> None:
    a = _candidate("Provision the venv, before first use.", 9)
    b = _candidate("provision the venv before first use", 9)

    assert candidate_key(a) == candidate_key(b)


def test_candidate_key_differs_for_different_lessons() -> None:
    assert candidate_key(_candidate("one lesson", 3)) != candidate_key(_candidate("another", 3))


def test_issue_key_is_repo_qualified() -> None:
    assert issue_key("oversteward", 327) == "issue:oversteward#327"


# --- verdict ledger ---------------------------------------------------------


def test_read_verdicts_is_empty_before_any_ruling(tmp_path) -> None:
    assert read_verdicts(tmp_path / "kaizen.json") == {}


def test_record_verdict_round_trips(tmp_path) -> None:
    path = tmp_path / "kaizen.json"

    record_verdict(path, key="abc123", verdict="promoted", on=date(2026, 8, 8), note="→ doctrine")

    verdicts = read_verdicts(path)
    assert verdicts["abc123"]["verdict"] == "promoted"
    assert verdicts["abc123"]["on"] == "2026-08-08"
    assert verdicts["abc123"]["note"] == "→ doctrine"


def test_record_verdict_rejects_an_unknown_verdict(tmp_path) -> None:
    with pytest.raises(ValueError):
        record_verdict(tmp_path / "k.json", key="a", verdict="maybe", on=date(2026, 8, 8))


def test_a_later_verdict_supersedes_an_earlier_one(tmp_path) -> None:
    path = tmp_path / "kaizen.json"

    record_verdict(path, key="abc", verdict="deferred", on=date(2026, 8, 1))
    record_verdict(path, key="abc", verdict="promoted", on=date(2026, 8, 8))

    assert read_verdicts(path)["abc"]["verdict"] == "promoted"


def test_read_verdicts_survives_a_corrupt_ledger(tmp_path) -> None:
    path = tmp_path / "kaizen.json"
    path.write_text("{not json", encoding="utf-8")

    assert read_verdicts(path) == {}


# --- queue ------------------------------------------------------------------


def test_build_queue_merges_both_sources() -> None:
    queue = build_queue(
        candidates=[_candidate("a recurring lesson", 9)],
        issues=[_issue(327, "a filed finding")],
        verdicts={},
    )

    assert {item.source for item in queue} == {"promotion", "issue"}


def test_build_queue_ranks_by_recurrence_with_issues_interleaved() -> None:
    queue = build_queue(
        candidates=[_candidate("low", 4), _candidate("high", 20)],
        issues=[_issue(327, "a filed finding")],
        verdicts={},
    )

    assert queue[0].title == "high"
    # A filed finding carries no recurrence count; it sorts below counted clusters
    # but is never dropped — it was filed precisely because someone judged it real.
    assert queue[-1].source == "issue"


def test_build_queue_excludes_resolved_candidates() -> None:
    resolved = _candidate("already ruled on", 30)
    verdicts = {candidate_key(resolved): {"verdict": "declined", "on": "2026-08-01"}}

    queue = build_queue(candidates=[resolved, _candidate("still open", 3)], issues=[], verdicts=verdicts)

    assert [item.title for item in queue] == ["still open"]


def test_build_queue_excludes_resolved_issues() -> None:
    verdicts = {issue_key("oversteward", 327): {"verdict": "promoted", "on": "2026-08-01"}}

    queue = build_queue(candidates=[], issues=[_issue(327, "done"), _issue(328, "open")], verdicts=verdicts)

    assert [item.reference for item in queue] == ["oversteward#328"]


def test_build_queue_keeps_a_deferred_item_available() -> None:
    """`deferred` records a decision to wait, not a decision to drop."""
    deferred = _candidate("come back to this", 12)
    verdicts = {candidate_key(deferred): {"verdict": "deferred", "on": "2026-08-01"}}

    queue = build_queue(candidates=[deferred], issues=[], verdicts=verdicts)

    assert [item.title for item in queue] == ["come back to this"]


def test_build_queue_ignores_issues_without_the_kaizen_label() -> None:
    queue = build_queue(
        candidates=[],
        issues=[_issue(400, "unrelated", labels=("bug",)), _issue(327, "real", labels=("kaizen",))],
        verdicts={},
    )

    assert [item.reference for item in queue] == ["oversteward#327"]


# --- next item / rendering --------------------------------------------------


def test_next_item_returns_the_head_of_the_queue() -> None:
    queue = build_queue(candidates=[_candidate("top", 20), _candidate("second", 5)], issues=[], verdicts={})

    assert next_item(queue).title == "top"


def test_next_item_is_none_on_an_empty_queue() -> None:
    assert next_item([]) is None


def test_format_next_carries_the_evidence() -> None:
    item = KaizenItem(
        key="abc",
        source="promotion",
        title="provision the venv before first use",
        reference="oversteward#100",
        count=9,
        target="doctrine",
        detail="contributing PRs: oversteward#100",
    )

    rendered = format_next(item, queue_size=7)

    assert "provision the venv" in rendered
    assert "9" in rendered
    assert "doctrine" in rendered
    assert "7" in rendered


def test_format_next_reports_an_empty_queue_as_a_measured_result() -> None:
    rendered = format_next(None, queue_size=0)

    assert "nothing queued" in rendered.lower()


def test_build_queue_propagates_the_false_green_guard() -> None:
    """An empty backlog must never be reported when the detector is broken.

    `build_queue` takes already-built candidates, so the guard rides on the
    caller — but a caller that passes an unmeasurable report must not get a
    cheerful empty queue. Pinned here so the CLI wiring cannot regress it.
    """
    with pytest.raises(FalseGreenError):
        build_queue(candidates=[], issues=[], verdicts={}, report={
            "recurring_drag": [],
            "candidate_lessons": [],
            "per_repo_counts": [{"repo": "oversteward", "count": 400}],
        })
