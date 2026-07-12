# ABOUTME: Fixture tests for the Vintner funnel logic — coverage%, drop-off, velocity, freshness, verdict, AG-visibility.
# ABOUTME: Pure logic, no DB. Deterministic clock injected via now=.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from oversteward.vintner.funnel import (
    FOUNDATIONS_WITH_SITEMAP,
    GOV_OPPS_GRANT_RELEVANT,
    build_report,
    snapshot_counts,
)
from oversteward.vintner.models import StageRow, StageState

NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fresh(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def _rows() -> list[StageRow]:
    return [
        StageRow(1, "foundations_total", 300_000, None),
        StageRow(2, "grantmakers_active", 120_000, _fresh(2)),
        StageRow(3, "gov_opps_total", 26_000, _fresh(1)),
        StageRow(4, "gov_opps_grant_relevant", 34_000, _fresh(1)),
        StageRow(5, "foundations_with_website", 100_000, _fresh(5)),
        StageRow(6, "foundations_with_sitemap", 40_000, _fresh(3)),
        StageRow(7, "websites_crawled", 36_000, _fresh(10)),
        StageRow(8, "enrichments_active", 0, None),
        StageRow(9, "missions_present", 8_000, _fresh(200)),
        StageRow(10, "deadlines_present", 500, _fresh(400)),
        StageRow(11, "display_name_present", 0, None),
    ]


def _by_stage(report):
    return {s.stage: s for s in report.stages}


def test_coverage_pct_is_child_over_parent():
    report = build_report(_rows(), now=NOW)
    stages = _by_stage(report)
    # websites_crawled / foundations_with_website = 36000 / 100000 = 36%
    assert stages["websites_crawled"].coverage_pct == 36.0
    # grantmakers_active / foundations_total = 120000 / 300000 = 40%
    assert stages["grantmakers_active"].coverage_pct == 40.0


def test_funnel_head_has_no_coverage():
    stages = _by_stage(build_report(_rows(), now=NOW))
    assert stages["foundations_total"].coverage_pct is None
    assert stages["gov_opps_total"].coverage_pct is None


def test_first_run_has_no_velocity():
    report = build_report(_rows(), previous=None, now=NOW)
    assert report.has_velocity is False
    assert all(s.delta is None for s in report.stages)


def test_second_run_shows_delta():
    previous = {"websites_crawled": 30_000, "foundations_total": 300_000}
    report = build_report(_rows(), previous=previous, now=NOW)
    assert report.has_velocity is True
    stages = _by_stage(report)
    assert stages["websites_crawled"].delta == 6_000
    assert stages["foundations_total"].delta == 0
    # A stage absent from the prior snapshot gets no delta, not a spurious jump.
    assert stages["gov_opps_total"].delta is None


def test_schema_drift_verdict_when_view_stages_diverge():
    # The 2026-07-11 incident: the deployed view still carried the pre-#149/#154
    # stage set (sitemaps_discovered, gov_opps_open_or_rolling, and a
    # status-predicate websites_crawled reporting 49) while the spine expected
    # the corrected vocabulary. The spine rendered it without complaint.
    # Divergent stage names must outrank every other verdict.
    rows = _rows()
    rows[3] = StageRow(4, "gov_opps_open_or_rolling", 455_000, _fresh(1))
    rows[5] = StageRow(6, "sitemaps_discovered", 13_000_000, _fresh(3))
    report = build_report(rows, now=NOW)
    assert report.verdict.startswith("SCHEMA DRIFT")
    assert "gov_opps_open_or_rolling" in report.verdict  # unexpected
    assert "sitemaps_discovered" in report.verdict  # unexpected
    assert GOV_OPPS_GRANT_RELEVANT in report.verdict  # missing
    assert FOUNDATIONS_WITH_SITEMAP in report.verdict  # missing


def test_matching_stage_set_reports_no_drift():
    report = build_report(_rows(), now=NOW)
    assert "SCHEMA DRIFT" not in report.verdict


def test_freshness_states():
    stages = _by_stage(build_report(_rows(), now=NOW))
    assert stages["grantmakers_active"].state is StageState.RUNNING  # 2h
    # 200h = 8.3d > 168h (7d) => STOPPED (kill-switched enrichment surfaces here)
    assert stages["missions_present"].state is StageState.STOPPED
    assert stages["deadlines_present"].state is StageState.STOPPED  # 400h
    assert stages["enrichments_active"].state is StageState.EMPTY  # 0 rows
    assert stages["display_name_present"].state is StageState.EMPTY  # 0 rows
    # newest_at present but no rows still reads as EMPTY; no stamp + rows => UNKNOWN
    assert stages["foundations_total"].state is StageState.UNKNOWN  # rows, no stamp


def test_running_boundary_48h():
    rows = [StageRow(1, "foundations_total", 10, _fresh(47))]
    assert _by_stage(build_report(rows, now=NOW))["foundations_total"].state is StageState.RUNNING
    rows = [StageRow(1, "foundations_total", 10, _fresh(49))]
    assert _by_stage(build_report(rows, now=NOW))["foundations_total"].state is StageState.STALE


def test_naive_timestamp_treated_as_utc():
    naive = datetime(2026, 7, 1, 10, 0, 0)  # 2h before NOW, no tzinfo
    rows = [StageRow(1, "foundations_total", 10, naive)]
    stage = _by_stage(build_report(rows, now=NOW))["foundations_total"]
    assert stage.age_hours == 2.0
    assert stage.state is StageState.RUNNING


def test_ag_visibility_flags():
    stages = _by_stage(build_report(_rows(), now=NOW))
    assert stages["foundations_total"].ag_visible is True
    assert stages["missions_present"].ag_visible is True
    assert stages["websites_crawled"].ag_visible is False
    assert stages["foundations_with_sitemap"].ag_visible is False
    assert stages["deadlines_present"].ag_visible is False
    assert stages["enrichments_active"].ag_visible is False


def test_verdict_stopped_dominates():
    report = build_report(_rows(), now=NOW)
    assert report.verdict.startswith("STOPPED")


def _all_fresh_rows() -> list[StageRow]:
    """A full valid stage set, every stage fresh and populated.

    Verdict fixtures need the complete vocabulary — a partial stage list now
    (correctly) reports SCHEMA DRIFT before any freshness verdict.
    """
    ordered = sorted(_rows(), key=lambda r: r.stage_order)
    return [
        StageRow(row.stage_order, row.stage, 1_000, _fresh(1)) for row in ordered
    ]


def test_verdict_healthy_when_all_fresh_and_populated():
    assert build_report(_all_fresh_rows(), now=NOW).verdict.startswith("HEALTHY")


def test_verdict_gaps_when_empty_but_no_stopped():
    rows = _all_fresh_rows()
    rows[1] = StageRow(2, "grantmakers_active", 0, None)
    assert build_report(rows, now=NOW).verdict.startswith("GAPS")


def test_verdict_slowing_when_stale_but_no_stopped_or_empty():
    rows = _all_fresh_rows()
    rows[1] = StageRow(2, "grantmakers_active", 50, _fresh(72))
    assert build_report(rows, now=NOW).verdict.startswith("SLOWING")


def test_snapshot_counts_roundtrip():
    report = build_report(_rows(), now=NOW)
    counts = snapshot_counts(report)
    assert counts["foundations_total"] == 300_000
    assert counts["enrichments_active"] == 0
    assert len(counts) == 11


def test_stages_sorted_by_stage_order():
    shuffled = list(reversed(_rows()))
    report = build_report(shuffled, now=NOW)
    orders = [s.stage_order for s in report.stages]
    assert orders == sorted(orders)


def test_zero_parent_count_yields_no_coverage():
    # parent present but count 0 => avoid division by zero, coverage is None
    rows = [
        StageRow(1, "foundations_total", 0, None),
        StageRow(2, "grantmakers_active", 0, None),
    ]
    stages = _by_stage(build_report(rows, now=NOW))
    assert stages["grantmakers_active"].coverage_pct is None
