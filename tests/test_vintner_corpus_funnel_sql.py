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

# The 11 funnel stages from issue #146, in order.
_EXPECTED_STAGES = [
    "foundations_total",
    "grantmakers_active",
    "gov_opps_total",
    "gov_opps_open_or_rolling",
    "sitemaps_discovered",
    "foundations_with_website",
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
    assert "close_date IS NULL" in sql_text
    assert "status IN ('fetched', 'parsed')" in sql_text
    assert "enrichment_status = 'active'" in sql_text


def test_balanced_parentheses_in_view_block(sql_text: str) -> None:
    marker = "CREATE OR REPLACE VIEW vintner.corpus_funnel_v AS"
    start = sql_text.index(marker)
    # The view definition ends at the terminating semicolon of the ORDER BY.
    end = sql_text.index("ORDER BY stage_order;", start) + len("ORDER BY stage_order;")
    block = sql_text[start:end]
    assert block.count("(") == block.count(")"), "unbalanced parentheses in view block"
