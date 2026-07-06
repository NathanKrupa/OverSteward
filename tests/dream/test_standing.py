# ABOUTME: Tests for the strict standing-orders classifier + renderer (OS#203) — the law/habit/graveyard/pointer gates.
# ABOUTME: The load-bearing case: a keyword-laden non-law must NOT be promoted; explicit tier overrides; sidecars excluded.

from __future__ import annotations

from oversteward.dream.consolidate import MemoryFile
from oversteward.dream.standing import (
    GRAVEYARD,
    HABIT,
    LAW,
    NON_STANDING,
    POINTER,
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


def test_retirement_signal_is_graveyard() -> None:
    mem = _mem(
        "gy_x",
        "Telegram removed; Happy adopted as live transport",
        body="Telegram was dropped and superseded by Happy — use Happy instead.\n",
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
    assert "law_x.md" in out
    assert "steward-variant" not in out


# ---- rendering ---------------------------------------------------------------


def test_render_groups_and_omits_empty_and_non_standing() -> None:
    law = _mem("law_x", "a law", provenance="nathan-stated")
    plain = _mem("ref_x", "a plain reference")
    out = render_standing_orders([law, plain])
    assert "# Standing Orders" in out
    assert "## Laws" in out
    assert "law_x.md" in out
    # Non-standing facts never appear; empty groups are omitted.
    assert "ref_x.md" not in out
    assert "## Graveyard" not in out


def test_render_uses_digest_when_set() -> None:
    law = _mem("law_x", "long recall hook", provenance="nathan-stated", digest="short imperative")
    out = render_standing_orders([law])
    assert "short imperative" in out


def test_render_shows_scope() -> None:
    law = _mem("law_x", "a law", provenance="nathan-stated", scope=["grantspider"])
    out = render_standing_orders([law])
    assert "scope: grantspider" in out
