# ABOUTME: Tests for the strict standing-orders classifier + renderer (OS#203) — the law/habit/graveyard/pointer gates.
# ABOUTME: The load-bearing case: a keyword-laden non-law must NOT be promoted; explicit tier overrides; sidecars excluded.

from __future__ import annotations

import pytest

from oversteward.dream.consolidate import MemoryFile
from oversteward.dream.standing import (
    GRAVEYARD,
    HABIT,
    LAW,
    NON_STANDING,
    POINTER,
    STANDING_LAYER_BYTE_BUDGET,
    StandingOrdersOverBudget,
    classify,
    is_steward_variant,
    render_standing_orders,
)


def _mem(
    name: str,
    description: str,
    *,
    type_: str = "feedback",
    provenance: str = "claude-inferred",
    body: str = "Some body text.\n",
    tier: str | None = None,
    scope: list[str] | None = None,
    digest: str | None = None,
    superseded_by: str | None = None,
) -> MemoryFile:
    metadata: dict[str, object] = {
        "type": type_,
        "provenance": provenance,
        "created": "2026-01-01",
        "last_reinforced": "2026-01-01",
        "confidence": "high",
        "decay_status": "active",
        "source_sessions": ["sess-1"],
    }
    if tier is not None:
        metadata["tier"] = tier
    if scope is not None:
        metadata["scope"] = scope
    if digest is not None:
        metadata["digest"] = digest
    if superseded_by is not None:
        metadata["superseded_by"] = superseded_by
    return MemoryFile(
        name=name,
        description=description,
        metadata=metadata,
        body=body,
        filename=f"{name}.md",
    )


# ---- the four standing kinds -------------------------------------------------


def test_type_user_is_a_law() -> None:
    mem = _mem("user_pref", "prefer merge commits", type_="user")
    assert classify(mem).kind == LAW


def test_feedback_nathan_stated_is_a_law() -> None:
    # A nathan-stated feedback fact is a durable law.
    mem = _mem("law_x", "agents are read-only on Neon", type_="feedback", provenance="nathan-stated")
    assert classify(mem).kind == LAW


def test_feedback_claude_inferred_is_not_a_law() -> None:
    # A claude-inferred feedback lesson is NOT constitutional.
    mem = _mem("fb_x", "a derived ops lesson", type_="feedback", provenance="claude-inferred")
    assert classify(mem).kind != LAW


def test_nathan_stated_project_datum_is_non_standing() -> None:
    # THE crux (OS#206): a durable nathan-stated project *datum* (an application
    # limit, a comp coupon) is recallable but NOT constitutional — it must NOT
    # derive to a law. It stays non-standing (recallable via the full index).
    mem = _mem(
        "proj_limits",
        "AG application limits: 20 pro / 50 consultant",
        type_="project",
        provenance="nathan-stated",
        body="Durable data, but not a law.\n",
    )
    assert classify(mem).kind == NON_STANDING


def test_nathan_stated_reference_datum_is_non_standing() -> None:
    # A nathan-stated reference datum (endpoint topology) is likewise not a law.
    mem = _mem(
        "ref_topology",
        "Neon endpoint topology for the research DB",
        type_="reference",
        provenance="nathan-stated",
        body="Durable connection facts, not constitutional.\n",
    )
    assert classify(mem).kind == NON_STANDING


def test_explicit_standing_tier_on_project_surfaces_in_layer() -> None:
    # The deliberate escape hatch: an explicit dream-written tier:standing forces
    # even a project fact into the always-loaded layer. It does not qualify as a
    # law on the tightened gate, so it surfaces as a habit — but it IS in the layer.
    mem = _mem(
        "proj_guardrail",
        "merging to GS master kills the in-flight Dagster run",
        type_="project",
        provenance="nathan-stated",
        tier="standing",
    )
    kind = classify(mem).kind
    assert kind != NON_STANDING
    assert kind == HABIT


def test_keyword_laden_non_law_is_not_promoted() -> None:
    # THE load-bearing case: "never/always/must" in an ordinary claude-inferred
    # ops lesson must NOT become a law. This is the exact inflation (~50 → 112)
    # the strict classifier exists to prevent.
    mem = _mem(
        "ops_lesson",
        "never migrate a shared prod DB; you must always back up first",
        type_="feedback",
        provenance="claude-inferred",
        body="Always back up before a destructive op. Never skip the check.\n",
    )
    assert classify(mem).kind != LAW


def test_explicit_superseded_by_is_graveyard() -> None:
    # Graveyard is now EXPLICIT-marker only (OS#206 follow-up): a memory carrying
    # metadata.superseded_by is the corpse — "reach for the replacement".
    mem = _mem(
        "gy_x",
        "Telegram removed; Happy adopted as live transport",
        superseded_by="Happy",
    )
    assert classify(mem).kind == GRAVEYARD


def test_retirement_vocabulary_alone_is_not_graveyard() -> None:
    # THE load-bearing change: retirement words appear incidentally in ordinary
    # facts ("when load is removed", "the dead url_type column", "renders an
    # obsolete vocabulary"). Without an explicit marker, keyword presence must NOT
    # drag a fact into the always-loaded Graveyard.
    mem = _mem(
        "not_gy",
        "AG renders an obsolete enrichment vocabulary; producer types render blank",
        body="A stale column was dropped upstream; the endpoint was retired and "
        "superseded by a new one — but this fact is project state, not a redirect.\n",
    )
    assert classify(mem).kind != GRAVEYARD


def test_superseded_by_outranks_explicit_tier() -> None:
    # A retirement warning is actively harmful to ignore, so the graveyard marker
    # surfaces in the always-loaded layer even against an explicit demoting tier.
    mem = _mem(
        "gy_tier",
        "the old two-stage verify path",
        tier="cookbook",
        superseded_by="single-pass self-verifying drain",
    )
    assert classify(mem).kind == GRAVEYARD


def test_living_doc_subject_is_a_pointer() -> None:
    mem = _mem(
        "ptr_x",
        "read data/tool_registry.md before grepping for a tool",
        body="The tool_registry.md catalog lists every CLI entry point.\n",
    )
    assert classify(mem).kind == POINTER


def test_plain_reference_is_non_standing() -> None:
    mem = _mem(
        "ref_plain",
        "the SAM proxy occasionally read-times-out",
        body="Direct calls return 200; the proxy path times out intermittently.\n",
    )
    assert classify(mem).kind == NON_STANDING


# ---- explicit tier override --------------------------------------------------


def test_explicit_standing_tier_keeps_a_non_law_as_habit() -> None:
    mem = _mem("h_x", "a plain fact", tier="standing")
    assert classify(mem).kind == HABIT


def test_explicit_cookbook_tier_demotes_out_of_standing() -> None:
    # Even a nathan-stated fact is forced non-standing by an explicit cookbook tier.
    mem = _mem("c_x", "a recipe", provenance="nathan-stated", tier="cookbook")
    assert classify(mem).kind == NON_STANDING


def test_explicit_model_tier_is_non_standing() -> None:
    mem = _mem("m_x", "shapes judgment", tier="model")
    assert classify(mem).kind == NON_STANDING


def test_scope_flows_through_classification() -> None:
    mem = _mem("law_s", "a law", provenance="nathan-stated", scope=["grantspider", "aigranthelper"])
    assert classify(mem).scope == ["grantspider", "aigranthelper"]


# ---- sidecar exclusion -------------------------------------------------------


def test_sidecar_detected() -> None:
    assert is_steward_variant("feedback_x.steward-variant.md")
    assert not is_steward_variant("feedback_x.md")


def test_variant_suffix_matches_reconciler() -> None:
    # standing.py redefines the suffix to avoid an import cycle; guard the mirror.
    from oversteward.dream.reconcile import STEWARD_VARIANT_SUFFIX as RECONCILE_SUFFIX
    from oversteward.dream.standing import STEWARD_VARIANT_SUFFIX as STANDING_SUFFIX

    assert STANDING_SUFFIX == RECONCILE_SUFFIX


def test_render_excludes_sidecars() -> None:
    law = _mem("law_x", "a law", provenance="nathan-stated")
    sidecar = MemoryFile(
        name="law_x.steward-variant",
        description="backup variant",
        metadata={"type": "user"},
        body="backup\n",
        filename="law_x.steward-variant.md",
    )
    out = render_standing_orders([law, sidecar])
    assert "a law" in out
    assert "backup variant" not in out
    assert "steward-variant" not in out


# ---- rendering ---------------------------------------------------------------


def test_render_groups_and_omits_empty_and_non_standing() -> None:
    law = _mem("law_x", "a law", provenance="nathan-stated")
    plain = _mem("ref_x", "a plain reference")
    out = render_standing_orders([law, plain])
    assert "# Standing Orders" in out
    assert "## Laws" in out
    assert "- a law" in out
    # Non-standing facts never appear; empty groups are omitted.
    assert "a plain reference" not in out
    assert "## Graveyard" not in out


def test_render_uses_digest_when_set() -> None:
    law = _mem("law_x", "long recall hook", provenance="nathan-stated", digest="short imperative")
    out = render_standing_orders([law])
    assert "short imperative" in out


def test_render_shows_scope() -> None:
    law = _mem("law_x", "a law", provenance="nathan-stated", scope=["grantspider"])
    out = render_standing_orders([law])
    assert "scope: grantspider" in out


def test_render_graveyard_shows_replacement() -> None:
    grave = _mem("gy_x", "Telegram interface removed", superseded_by="Happy")
    out = render_standing_orders([grave])
    assert "## Graveyard" in out
    assert "Telegram interface removed" in out
    # The always-loaded line points at the live replacement, not just the corpse.
    assert "Happy" in out


# ---- no link scaffolding + the byte budget (OS#287) --------------------------


def test_render_carries_no_link_scaffolding() -> None:
    # THE OS#287 case: the always-loaded layer states the orders; the
    # `[file](file)` recall hook belongs to MEMORY_FULL.md. Repeating each ~70-char
    # filename twice per entry spent 51% of the capped budget on paths.
    law = _mem("a_very_long_slugified_filename_law", "a law", provenance="nathan-stated")
    out = render_standing_orders([law])
    assert "- a law" in out
    assert "a_very_long_slugified_filename_law.md" not in out
    assert "](" not in out


def test_render_keeps_every_fact_when_links_are_dropped() -> None:
    # Dropping the scaffolding loses zero facts — each standing memory's text,
    # its scope, and a graveyard replacement all still render.
    law = _mem("law_x", "a scoped law", provenance="nathan-stated", scope=["grantspider"])
    habit = _mem("h_x", "a habit", tier="standing")
    grave = _mem("gy_x", "a corpse", superseded_by="the live path")
    pointer = _mem("p_x", "read architecture.md at scope time")
    out = render_standing_orders([law, habit, grave, pointer])
    for text in ("a scoped law", "a habit", "a corpse", "read architecture.md at scope time"):
        assert text in out
    assert "scope: grantspider" in out
    assert "→ the live path" in out


def test_render_under_budget_is_clean() -> None:
    # A normal store renders without complaint and comfortably under the cap.
    memories = [_mem(f"law_{i}", f"standing order number {i}", type_="user") for i in range(40)]
    out = render_standing_orders(memories)
    assert len(out.encode("utf-8")) < STANDING_LAYER_BYTE_BUDGET
    assert "standing order number 39" in out


def test_render_over_budget_fails_loudly() -> None:
    # A store large enough to breach the cap must RAISE, not emit a layer the
    # harness would silently truncate (which is the defect this budget exists for).
    filler = "x" * 500
    memories = [_mem(f"law_{i:03d}", f"{filler} {i}", type_="user") for i in range(60)]
    with pytest.raises(StandingOrdersOverBudget) as excinfo:
        render_standing_orders(memories)
    message = str(excinfo.value)
    assert str(STANDING_LAYER_BYTE_BUDGET) in message
    assert "over by" in message
    # The message names the per-group cost so the operator knows what to shed.
    assert "## Laws — 60 entries" in message


def test_over_budget_message_reports_every_populated_section() -> None:
    filler = "y" * 500
    memories = [_mem(f"law_{i:03d}", f"{filler} {i}", type_="user") for i in range(60)]
    memories.append(_mem("gy_x", "a corpse", superseded_by="the live path"))
    with pytest.raises(StandingOrdersOverBudget) as excinfo:
        render_standing_orders(memories)
    message = str(excinfo.value)
    assert "## Laws — 60 entries" in message
    assert "## Graveyard — 1 entry," in message
    # Empty groups are not listed.
    assert "## Habits" not in message
