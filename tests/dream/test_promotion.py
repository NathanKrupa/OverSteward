# ABOUTME: Tests for the dream cycle's trajectory-promotion pass (design §13.5, OS#325).
# ABOUTME: Probe → report → worklist → packet, all against injected inputs.

from __future__ import annotations

from datetime import date

import pytest

from oversteward.dream.promotion import (
    HARD_CAP_DAYS,
    FalseGreenError,
    PromotionCandidate,
    build_worklist,
    default_promotion_ledger_path,
    format_packet,
    parse_promote_target,
    probe_due,
    read_clustering_status,
    read_last_run,
    read_run_history,
    record_run,
    verify_report_is_measurable,
)


def _cluster(text: str, count: int, *, target: str = "doctrine", repos=("oversteward",)):
    """A cluster in the shape `fiscus review trajectories --format json` emits."""
    return {
        "canonical_text": text,
        "category": "tooling",
        "count": count,
        "repos": list(repos),
        "items": [
            {
                "repo": repos[0],
                "pr": f"{repos[0]}#{100 + i}",
                "date": "2026-08-01",
                "bullet": f"[tooling] {text} → promote: {target}",
            }
            for i in range(count)
        ],
    }


# --- promote-target parsing -------------------------------------------------


@pytest.mark.parametrize(
    "bullet,expected",
    [
        ("[tooling] Provision the venv → promote: doctrine", "doctrine"),
        ("[design] Something → promote: memory.", "memory"),
        ("[process] Something → promote: lessons.jsonl", "lessons.jsonl"),
        ("[process] Something → promote: none", "none"),
        ("[process] A bullet with no promote tag at all", ""),
        ("[process] Off-vocabulary → promote: somewhere", ""),
    ],
)
def test_parse_promote_target(bullet: str, expected: str) -> None:
    assert parse_promote_target(bullet) == expected


# --- cadence probe ----------------------------------------------------------


def test_probe_due_when_never_run() -> None:
    probe = probe_due(None, today=date(2026, 8, 8))

    assert probe.due is True
    assert "never run" in " ".join(probe.reasons)


def test_probe_not_due_inside_the_window() -> None:
    probe = probe_due(date(2026, 8, 1), today=date(2026, 8, 8))

    assert probe.due is False
    assert probe.days_old == 7


def test_probe_due_past_the_hard_cap() -> None:
    stamp = date(2026, 7, 1)
    today = date(2026, 8, 8)

    probe = probe_due(stamp, today=today)

    assert probe.due is True
    assert probe.days_old == (today - stamp).days > HARD_CAP_DAYS


# --- the false-green guard --------------------------------------------------


def test_verify_report_rejects_zero_clusters_over_a_large_corpus() -> None:
    """Zero patterns across a large corpus is the false-green signature, not health.

    This is the guard the analyzer itself lacked for its whole life (Fiscus #101):
    it answered "no patterns detected" over 425 notes and nothing objected.
    """
    report = {"recurring_drag": [], "candidate_lessons": [], "notes": [{}] * 400}

    with pytest.raises(FalseGreenError) as excinfo:
        verify_report_is_measurable(report)

    assert "400" in str(excinfo.value)


def test_verify_report_accepts_zero_clusters_over_a_small_corpus() -> None:
    """A genuinely small corpus may legitimately have nothing recurring."""
    report = {"recurring_drag": [], "candidate_lessons": [], "notes": [{}] * 3}

    verify_report_is_measurable(report)  # does not raise


def test_verify_report_accepts_a_report_with_clusters() -> None:
    report = {
        "recurring_drag": [_cluster("a thing", 4)],
        "candidate_lessons": [],
        "notes": [{}] * 400,
    }

    verify_report_is_measurable(report)  # does not raise


# --- worklist ---------------------------------------------------------------


def test_build_worklist_keeps_only_promotable_targets() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [
            _cluster("promote me to doctrine", 5, target="doctrine"),
            _cluster("promote me to memory", 4, target="memory"),
            _cluster("explicitly not worth promoting", 9, target="none"),
            _cluster("belongs in the lessons corpus", 6, target="lessons.jsonl"),
        ],
        "notes": [{}] * 400,
    }

    worklist = build_worklist(report)

    targets = {c.target for c in worklist}
    assert targets == {"doctrine", "memory"}


def test_build_worklist_drops_clusters_below_min_recurrence() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [
            _cluster("recurs enough", 3),
            _cluster("too rare", 2),
        ],
        "notes": [{}] * 400,
    }

    worklist = build_worklist(report, min_recurrence=3)

    assert [c.count for c in worklist] == [3]


def test_build_worklist_ranks_by_recurrence_and_caps() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [_cluster(f"lesson {i}", i) for i in range(3, 12)],
        "notes": [{}] * 400,
    }

    worklist = build_worklist(report, cap=4)

    assert len(worklist) == 4
    assert [c.count for c in worklist] == [11, 10, 9, 8]


def test_build_worklist_spans_both_report_sections() -> None:
    report = {
        "recurring_drag": [_cluster("a recurring drag", 7)],
        "candidate_lessons": [_cluster("a candidate lesson", 5)],
        "notes": [{}] * 400,
    }

    worklist = build_worklist(report)

    assert {c.section for c in worklist} == {"recurring_drag", "candidate_lessons"}


def test_build_worklist_records_contributing_prs() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [_cluster("a lesson", 3)],
        "notes": [{}] * 400,
    }

    candidate = build_worklist(report)[0]

    assert candidate.prs == ["oversteward#100", "oversteward#101", "oversteward#102"]


def test_build_worklist_propagates_the_false_green_guard() -> None:
    report = {"recurring_drag": [], "candidate_lessons": [], "notes": [{}] * 400}

    with pytest.raises(FalseGreenError):
        build_worklist(report)


# --- packet -----------------------------------------------------------------


def test_format_packet_is_bounded_and_cites_evidence() -> None:
    candidates = [
        PromotionCandidate(
            canonical_text="provision the worktree venv before first use",
            category="tooling",
            count=9,
            repos=["oversteward", "grantspider"],
            target="doctrine",
            section="candidate_lessons",
            prs=["oversteward#100", "oversteward#101"],
        )
    ]

    packet = format_packet(candidates, generated_on=date(2026, 8, 8))

    assert "2026-08-08" in packet
    assert "provision the worktree venv" in packet
    assert "9" in packet
    assert "doctrine" in packet
    assert "oversteward#100" in packet


def test_format_packet_says_so_when_there_is_nothing_to_promote() -> None:
    packet = format_packet([], generated_on=date(2026, 8, 8))

    assert "nothing" in packet.lower()


# --- corpus size across BOTH report shapes ----------------------------------
#
# The single-repo report carries `notes`; the cross-repo (`--all-active`)
# report carries `per_repo_counts` instead. The cadence uses the cross-repo
# form, so a guard that only understands `notes` counts a 346-note corpus as
# empty and passes vacuously — a false green inside the false-green guard.


def test_verify_report_counts_the_cross_repo_corpus_shape() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [],
        "per_repo_counts": [
            {"repo": "oversteward", "count": 93},
            {"repo": "grantspider", "count": 127},
            {"repo": "aigranthelper", "count": 99},
        ],
    }

    with pytest.raises(FalseGreenError) as excinfo:
        verify_report_is_measurable(report)

    assert "319" in str(excinfo.value)


def test_verify_report_accepts_a_small_cross_repo_corpus() -> None:
    report = {
        "recurring_drag": [],
        "candidate_lessons": [],
        "per_repo_counts": [{"repo": "wphelper", "count": 3}],
    }

    verify_report_is_measurable(report)  # does not raise


def test_verify_report_refuses_a_report_with_no_corpus_signal_at_all() -> None:
    """Neither shape present means the corpus size is unknown, not zero.

    "Could not look" must never resolve to the same verdict as "looked and the
    corpus was small" — that is precisely how a broken instrument reads healthy.
    """
    with pytest.raises(FalseGreenError):
        verify_report_is_measurable({"recurring_drag": [], "candidate_lessons": []})


# --- clustering provenance (OS#352 / Fiscus #119) ---------------------------


def test_read_clustering_status_reads_a_semantic_report() -> None:
    status = read_clustering_status({"clustering": {"mode": "semantic", "degraded": False}})

    assert status.reported
    assert status.mode == "semantic"
    assert status.degraded is False
    assert status.measured


def test_read_clustering_status_reads_the_degraded_lexical_fallback() -> None:
    status = read_clustering_status({"clustering": {"mode": "lexical", "degraded": True}})

    assert status.degraded is True
    assert status.lexical
    assert not status.measured


def test_read_clustering_status_keeps_requested_lexical_distinct_from_a_fallback() -> None:
    """`--no-semantic` is an operator choice, not a degradation — but still unmeasured."""
    status = read_clustering_status({"clustering": {"mode": "lexical", "degraded": False}})

    assert status.degraded is False
    assert status.lexical
    assert not status.measured


def test_read_clustering_status_reports_an_absent_block_as_unknown() -> None:
    """A report from a fiscus predating #119 says nothing — which is not "semantic"."""
    status = read_clustering_status({"candidate_lessons": []})

    assert status.reported is False
    assert status.mode is None
    assert status.degraded is False
    assert not status.measured


def test_read_clustering_status_treats_a_malformed_block_as_unknown() -> None:
    """"Could not read the mode" must land on the unknown branch, never on measured."""
    assert not read_clustering_status({"clustering": "semantic"}).reported
    assert not read_clustering_status({"clustering": {"degraded": False}}).reported
    assert not read_clustering_status({"clustering": {"mode": 7}}).reported


def test_read_clustering_status_does_not_call_an_unfamiliar_mode_measured() -> None:
    status = read_clustering_status({"clustering": {"mode": "hierarchical", "degraded": False}})

    assert status.reported
    assert status.mode == "hierarchical"
    assert not status.measured
    assert not status.lexical


# --- run ledger -------------------------------------------------------------


def test_default_promotion_ledger_path_sits_with_the_other_dream_state(tmp_path) -> None:
    assert default_promotion_ledger_path(tmp_path) == tmp_path / "data" / "dream" / "promotion.json"


def test_read_last_run_is_none_before_the_first_pass(tmp_path) -> None:
    assert read_last_run(tmp_path / "data" / "dream" / "promotion.json") is None


def test_record_run_then_read_round_trips(tmp_path) -> None:
    path = tmp_path / "data" / "dream" / "promotion.json"

    record_run(path, ran_on=date(2026, 8, 8), candidates=3)

    assert read_last_run(path) == date(2026, 8, 8)


def test_record_run_keeps_prior_runs_so_a_missed_month_is_visible(tmp_path) -> None:
    path = tmp_path / "data" / "dream" / "promotion.json"

    record_run(path, ran_on=date(2026, 6, 1), candidates=5)
    record_run(path, ran_on=date(2026, 8, 8), candidates=2)

    history = read_run_history(path)
    assert [entry["ran_on"] for entry in history] == ["2026-06-01", "2026-08-08"]
    assert read_last_run(path) == date(2026, 8, 8)


def test_read_last_run_survives_a_corrupt_ledger(tmp_path) -> None:
    """A damaged ledger must read as "never run", not crash the dream cycle."""
    path = tmp_path / "data" / "dream" / "promotion.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert read_last_run(path) is None
