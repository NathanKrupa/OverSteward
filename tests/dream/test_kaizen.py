# ABOUTME: Tests for the session-start kaizen queue (OS#332) — verdicts, merge, ranking, next item.
# ABOUTME: All against injected inputs; nothing here touches the live ledger or GitHub.

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

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
from oversteward.dream.promotion import (
    FalseGreenError,
    PromotionCandidate,
    read_clustering_status,
)


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


# --- clustering provenance in the surface (OS#352) --------------------------


def _rendered(report_clustering: dict | None, *, count: int = 6) -> str:
    """`format_next` for one counted item, under the clustering the report declares."""
    report = dict(report_clustering) if report_clustering else {}
    item = KaizenItem(
        key="abc",
        source="promotion",
        title="a lesson the detector says recurs",
        reference="oversteward#297",
        count=count,
        target="doctrine",
        detail=f"{count}x across oversteward",
    )
    return format_next(item, queue_size=3, clustering=read_clustering_status(report))


def test_a_degraded_report_banners_above_the_item() -> None:
    rendered = _rendered({"clustering": {"mode": "lexical", "degraded": True}})

    assert "DEGRADED" in rendered
    # The banner is above the item, not a footnote below it.
    assert rendered.index("DEGRADED") < rendered.index("a lesson the detector says recurs")


def test_a_degraded_report_marks_every_recurrence_count_unmeasured() -> None:
    rendered = _rendered({"clustering": {"mode": "lexical", "degraded": True}})

    assert "6x recurrence (UNMEASURED" in rendered
    assert "read the cluster members before trusting the rank" in rendered


def test_a_requested_lexical_report_is_also_marked_unmeasured_but_not_degraded() -> None:
    """Lexical counts are artifacts however the mode was chosen; only the banner differs."""
    rendered = _rendered({"clustering": {"mode": "lexical", "degraded": False}})

    assert "UNMEASURED" in rendered
    assert "DEGRADED" not in rendered


def test_a_semantic_report_renders_exactly_as_before() -> None:
    rendered = _rendered({"clustering": {"mode": "semantic", "degraded": False}})

    assert "6x recurrence" in rendered
    assert "UNMEASURED" not in rendered
    assert "DEGRADED" not in rendered
    assert "clustering mode" not in rendered.lower()


def test_a_report_without_a_clustering_block_carries_a_caveat() -> None:
    """Absent is not semantic — "could not look" must not print as "found nothing"."""
    rendered = _rendered(None)

    assert "does not report its clustering mode" in rendered
    assert "lexical" in rendered
    assert "DEGRADED" not in rendered
    assert rendered.index("does not report") < rendered.index("a lesson the detector")


def test_an_unfamiliar_clustering_mode_is_caveated_rather_than_trusted() -> None:
    rendered = _rendered({"clustering": {"mode": "hierarchical", "degraded": False}})

    assert "hierarchical" in rendered
    assert "DEGRADED" not in rendered


def test_the_degradation_banner_also_covers_an_empty_queue() -> None:
    """A degraded run reporting "nothing queued" is the most misleading case of all."""
    status = read_clustering_status({"clustering": {"mode": "lexical", "degraded": True}})

    rendered = format_next(None, queue_size=0, clustering=status)

    assert "DEGRADED" in rendered
    assert "nothing queued" in rendered.lower()


def test_format_next_without_a_clustering_argument_is_silent_about_mode() -> None:
    """`kaizen next` run with no report at all has no counted clusters to caveat."""
    rendered = format_next(
        KaizenItem(
            key="k",
            source="issue",
            title="a filed finding",
            reference="oversteward#352",
            count=0,
            target="issue",
            detail="filed finding",
        ),
        queue_size=1,
    )

    assert "DEGRADED" not in rendered
    assert "UNMEASURED" not in rendered
    assert "clustering mode" not in rendered.lower()


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


# --- the CLI's exit-code contract (OS#352) ----------------------------------


def _dream_cli():
    """The `scripts/dream.py` CLI, loaded by path — `scripts/` is not a package."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "dream.py"
    spec = importlib.util.spec_from_file_location("dream_cli_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _degraded_report_file(tmp_path: Path) -> Path:
    report = {
        "clustering": {"mode": "lexical", "degraded": True},
        "per_repo_counts": [{"repo": "oversteward", "count": 400}],
        "candidate_lessons": [
            {
                "canonical_text": "a lexically glued cluster",
                "category": "tooling",
                "count": 6,
                "repos": ["oversteward"],
                "items": [
                    {"repo": "oversteward", "pr": f"oversteward#{300 + i}", "date": "2026-08-01",
                     "bullet": "[tooling] a lexically glued cluster → promote: doctrine"}
                    for i in range(6)
                ],
            }
        ],
    }
    path = tmp_path / "patterns.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_kaizen_next_stays_exit_0_on_a_degraded_report_and_says_so(tmp_path, capsys) -> None:
    """Degraded is loud, not fatal: a fallback report still surfaces real lessons.

    Exit 2 stays reserved for the empty-over-a-large-corpus case, so "the
    detector is broken" and "the detector is coarse" do not render the same.
    """
    code = _dream_cli().main(
        [
            "kaizen",
            "next",
            "--report",
            str(_degraded_report_file(tmp_path)),
            "--ledger",
            str(tmp_path / "kaizen.json"),
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "DEGRADED" in out
    assert "6x recurrence (UNMEASURED" in out
