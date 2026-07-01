# ABOUTME: Structural checks for vintner.corpus_funnel_v in the grantspider provisioning SQL.
# ABOUTME: No DB harness — asserts the view + grant text is present, well-formed, and covers all 11 stages.

from __future__ import annotations

from pathlib import Path

import pytest

_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "documentation"
    / "designs"
    / "vintner"
    / "provision_vintner_reader.grantspider.sql"
)

# The 11 funnel stages, in order. Stages 5-7 corrected in issue #149:
# foundations_with_website → foundations_with_sitemap → websites_crawled.
_EXPECTED_STAGES = [
    "foundations_total",
    "grantmakers_active",
    "gov_opps_total",
    "gov_opps_open_or_rolling",
    "foundations_with_website",
    "foundations_with_sitemap",
    "websites_crawled",
    "enrichments_active",
    "missions_present",
    "deadlines_present",
    "display_name_present",
]


@pytest.fixture(scope="module")
def sql_text() -> str:
    return _SQL_PATH.read_text(encoding="utf-8")


def test_provisioning_sql_exists() -> None:
    assert _SQL_PATH.is_file()


def test_view_defined(sql_text: str) -> None:
    assert "CREATE OR REPLACE VIEW vintner.corpus_funnel_v AS" in sql_text


def test_view_exposes_the_funnel_columns(sql_text: str) -> None:
    # One row per stage: (stage_order, stage, count, newest_at).
    for column in ("AS stage_order", "AS stage", "AS count", "AS newest_at"):
        assert column in sql_text, f"missing funnel column alias: {column}"


def test_all_stages_present(sql_text: str) -> None:
    for stage in _EXPECTED_STAGES:
        assert f"'{stage}'" in sql_text, f"missing funnel stage: {stage}"


def test_grant_select_to_vintner_reader(sql_text: str) -> None:
    assert "GRANT SELECT ON vintner.corpus_funnel_v TO vintner_reader;" in sql_text


def test_no_base_table_grant_added(sql_text: str) -> None:
    # vintner_reader must never be granted directly on a public.* base table.
    lowered = sql_text.lower()
    assert "grant select on public." not in lowered
    assert "grant select on table public." not in lowered


def test_view_reads_expected_base_tables(sql_text: str) -> None:
    for table in (
        "public.foundations",
        "public.gov_opportunities",
        "public.sitemap_candidate_queue",
        "public.mine_urls",
        "public.enrichments",
        "public.foundation_deadlines",
    ):
        assert table in sql_text, f"funnel view should read {table}"


def test_key_predicates_present(sql_text: str) -> None:
    # Spot-check the load-bearing predicates from the issue table.
    assert "is_active_grantmaker = true" in sql_text
    assert "status IN ('posted', 'preview', 'forecasted')" in sql_text
    assert "enrichment_status = 'active'" in sql_text


def test_corrected_predicates_issue_149(sql_text: str) -> None:
    # Issue #149 corrected three stage predicates.
    # 1. gov_opps_open_or_rolling: closed rows (close_date IS NULL) no longer
    #    slip through — status AND (rolling OR future close_date).
    assert (
        "status IN ('posted', 'preview', 'forecasted')\n"
        "                        AND (close_date IS NULL OR close_date >= now())"
    ) in sql_text
    # The old no-op `OR close_date IS NULL` clause is gone from the view body
    # (it survives only in the explanatory comment above the view).
    view_start = sql_text.index("CREATE OR REPLACE VIEW vintner.corpus_funnel_v AS")
    view_end = sql_text.index("ORDER BY stage_order;", view_start)
    view_body = sql_text[view_start:view_end]
    assert "OR close_date IS NULL" not in view_body
    # 2. foundations_with_sitemap counts DISTINCT foundations, not PAGE rows.
    assert "count(DISTINCT foundation_id)" in view_body
    assert "'sitemaps_discovered'" not in view_body
    # 3. websites_crawled uses the durable markdown-snapshot crawl signal,
    #    per DISTINCT domain — not the transient status IN ('fetched','parsed').
    assert "count(DISTINCT domain) FILTER (WHERE markdown_snapshot_at IS NOT NULL)" in view_body
    assert "status IN ('fetched', 'parsed')" not in view_body


def test_balanced_parentheses_in_view_block(sql_text: str) -> None:
    marker = "CREATE OR REPLACE VIEW vintner.corpus_funnel_v AS"
    start = sql_text.index(marker)
    # The view definition ends at the terminating semicolon of the ORDER BY.
    end = sql_text.index("ORDER BY stage_order;", start) + len("ORDER BY stage_order;")
    block = sql_text[start:end]
    assert block.count("(") == block.count(")"), "unbalanced parentheses in view block"
