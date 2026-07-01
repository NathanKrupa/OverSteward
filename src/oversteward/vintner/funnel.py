# ABOUTME: Deterministic funnel logic — coverage %, drop-off, velocity, freshness->running/stopped, AG-visible gap, verdict.
# ABOUTME: Pure Python (no DB, no LLM). Fixture-testable core of the Vintner's /pipeline-status report.

from __future__ import annotations

from datetime import datetime, timezone

from .models import FunnelReport, StageReport, StageRow, StageState

# Stage identifiers — the contract of vintner.corpus_funnel_v (stage column).
# Named once here so the parent map and AG-visibility set share one vocabulary.
FOUNDATIONS_TOTAL = "foundations_total"
GRANTMAKERS_ACTIVE = "grantmakers_active"
GOV_OPPS_TOTAL = "gov_opps_total"
GOV_OPPS_GRANT_RELEVANT = "gov_opps_grant_relevant"
FOUNDATIONS_WITH_WEBSITE = "foundations_with_website"
FOUNDATIONS_WITH_SITEMAP = "foundations_with_sitemap"
WEBSITES_CRAWLED = "websites_crawled"
ENRICHMENTS_ACTIVE = "enrichments_active"
MISSIONS_PRESENT = "missions_present"
DEADLINES_PRESENT = "deadlines_present"
DISPLAY_NAME_PRESENT = "display_name_present"

# Logical parent of each stage for drop-off / coverage%: numerator's count
# divided by its parent's count. A stage with no parent (funnel head, or a
# metric measured against a different universe) reports no coverage%.
STAGE_PARENT: dict[str, str | None] = {
    FOUNDATIONS_TOTAL: None,
    GRANTMAKERS_ACTIVE: FOUNDATIONS_TOTAL,
    GOV_OPPS_TOTAL: None,
    GOV_OPPS_GRANT_RELEVANT: GOV_OPPS_TOTAL,
    FOUNDATIONS_WITH_WEBSITE: GRANTMAKERS_ACTIVE,
    FOUNDATIONS_WITH_SITEMAP: FOUNDATIONS_WITH_WEBSITE,
    WEBSITES_CRAWLED: FOUNDATIONS_WITH_WEBSITE,
    ENRICHMENTS_ACTIVE: WEBSITES_CRAWLED,
    MISSIONS_PRESENT: FOUNDATIONS_WITH_WEBSITE,
    DEADLINES_PRESENT: FOUNDATIONS_WITH_WEBSITE,
    DISPLAY_NAME_PRESENT: FOUNDATIONS_TOTAL,
}

# Only foundations_v / grants_v reach the AG matchmaker. Every crawl, sitemap,
# deadline, and enrichment stage is structurally invisible to AG. A stage is
# AG-visible when its data flows through one of the exposed research views.
AG_VISIBLE_STAGES: frozenset[str] = frozenset(
    {
        FOUNDATIONS_TOTAL,
        GRANTMAKERS_ACTIVE,
        FOUNDATIONS_WITH_WEBSITE,
        MISSIONS_PRESENT,
        DISPLAY_NAME_PRESENT,
    }
)

# Freshness thresholds (hours). The enrichment stages are fed by a kill-switched
# stage: an old newest_at is the tell that the stage is OFF, not healthy.
RUNNING_MAX_AGE_HOURS = 48.0
STALE_MAX_AGE_HOURS = 168.0  # 7 days; older => treat as stopped


def _age_hours(newest_at: datetime | None, now: datetime) -> float | None:
    if newest_at is None:
        return None
    stamp = newest_at if newest_at.tzinfo else newest_at.replace(tzinfo=timezone.utc)
    return (now - stamp).total_seconds() / 3600.0


def _stage_state(count: int, age_hours: float | None) -> StageState:
    if count == 0:
        return StageState.EMPTY
    if age_hours is None:
        return StageState.UNKNOWN
    if age_hours <= RUNNING_MAX_AGE_HOURS:
        return StageState.RUNNING
    if age_hours <= STALE_MAX_AGE_HOURS:
        return StageState.STALE
    return StageState.STOPPED


def _coverage_pct(count: int, parent_count: int | None) -> float | None:
    if parent_count is None or parent_count == 0:
        return None
    return 100.0 * count / parent_count


def _stage_report(
    row: StageRow,
    counts: dict[str, int],
    previous: dict[str, int] | None,
    now: datetime,
) -> StageReport:
    parent = STAGE_PARENT.get(row.stage)
    parent_count = counts.get(parent) if parent else None
    age = _age_hours(row.newest_at, now)
    delta = None
    if previous is not None and row.stage in previous:
        delta = row.count - previous[row.stage]
    return StageReport(
        stage_order=row.stage_order,
        stage=row.stage,
        count=row.count,
        newest_at=row.newest_at,
        parent=parent,
        coverage_pct=_coverage_pct(row.count, parent_count),
        delta=delta,
        age_hours=age,
        state=_stage_state(row.count, age),
        ag_visible=row.stage in AG_VISIBLE_STAGES,
    )


def build_report(
    rows: list[StageRow],
    previous: dict[str, int] | None = None,
    now: datetime | None = None,
) -> FunnelReport:
    """Compute the full funnel report from raw view rows.

    ``previous`` maps stage -> prior count (from the persisted run snapshot);
    when present, each stage gets a velocity delta and the report is flagged
    as carrying velocity. ``now`` is injected for deterministic tests.
    """
    now = now or datetime.now(timezone.utc)
    counts = {r.stage: r.count for r in rows}
    reports = tuple(
        _stage_report(row, counts, previous, now)
        for row in sorted(rows, key=lambda r: r.stage_order)
    )
    return FunnelReport(
        generated_at=now,
        stages=reports,
        has_velocity=bool(previous),
        verdict=_verdict(list(reports)),
    )


def _verdict(reports: list[StageReport]) -> str:
    """One-glance top-line: worst structural signal across the funnel."""
    sep = ", "
    stopped = [r.stage for r in reports if r.state is StageState.STOPPED]
    empty = [r.stage for r in reports if r.state is StageState.EMPTY]
    stale = [r.stage for r in reports if r.state is StageState.STALE]

    if stopped:
        return f"STOPPED — {len(stopped)} stage(s) have gone cold: {sep.join(stopped)}."
    if empty:
        return f"GAPS — {len(empty)} stage(s) empty (0 rows): {sep.join(empty)}."
    if stale:
        return f"SLOWING — {len(stale)} stage(s) stale (>{int(RUNNING_MAX_AGE_HOURS)}h): {sep.join(stale)}."
    return "HEALTHY — every stage fresh and populated."


def snapshot_counts(report: FunnelReport) -> dict[str, int]:
    """Extract the stage->count map to persist for next run's velocity."""
    return {r.stage: r.count for r in report.stages}
