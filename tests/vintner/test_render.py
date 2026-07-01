# ABOUTME: Tests for the funnel renderer — table shape, verdict line, velocity note, AG-visible gap callout.
# ABOUTME: Pure formatting; asserts on the produced markdown text.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from oversteward.vintner.funnel import build_report
from oversteward.vintner.models import StageRow
from oversteward.vintner.render import render

NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _rows():
    return [
        StageRow(1, "foundations_total", 300_000, None),
        StageRow(6, "foundations_with_website", 100_000, NOW - timedelta(hours=5)),
        StageRow(7, "websites_crawled", 36_000, NOW - timedelta(hours=10)),
    ]


def test_render_has_verdict_and_table_header():
    out = render(build_report(_rows(), now=NOW))
    assert "**Verdict:**" in out
    assert "| Stage | Count | Coverage | Δ since last | Freshness | State | AG-visible |" in out


def test_first_run_shows_velocity_note():
    out = render(build_report(_rows(), previous=None, now=NOW))
    assert "First run" in out


def test_second_run_omits_velocity_note_and_shows_delta():
    previous = {"websites_crawled": 30_000}
    out = render(build_report(_rows(), previous=previous, now=NOW))
    assert "First run" not in out
    assert "+6,000" in out


def test_counts_are_thousands_grouped():
    out = render(build_report(_rows(), now=NOW))
    assert "300,000" in out


def test_ag_gap_callout_lists_invisible_stages():
    out = render(build_report(_rows(), now=NOW))
    assert "AG-visible gap" in out
    assert "websites_crawled" in out
    assert "INVISIBLE" in out


def test_coverage_percent_rendered():
    out = render(build_report(_rows(), now=NOW))
    # websites_crawled / foundations_with_website = 36%
    assert "36.0%" in out


def test_deterministic_footer_mentions_read_only_no_llm():
    out = render(build_report(_rows(), now=NOW))
    assert "read-only via vintner_reader" in out
    assert "zero LLM" in out
