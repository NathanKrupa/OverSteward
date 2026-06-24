# ABOUTME: Tests for dream-cycle extraction scaffolding — schema, prompt, signal gate, privacy filter, seam.
# ABOUTME: Uses a FAKE injected extractor and OBVIOUSLY-FAKE seeded secrets — never a real credential or LLM call.

from __future__ import annotations

import json

import pytest

from oversteward.dream.extract import (
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_VERSION,
    CandidateFact,
    CandidateValidationError,
    Extractor,
    build_extraction_prompt,
    extract_candidates,
    parse_candidates,
    privacy_filter,
    signal_gate,
)


def _fact(**overrides: object) -> CandidateFact:
    """A valid baseline candidate, overridable per field."""
    base = {
        "type": "feedback",
        "description": "merged GS migrations are not auto-applied to prod",
        "body": "Check alembic_version vs head and migrate-before-promote since prod deploys from main.",
        "provenance": "nathan-stated",
        "confidence": "high",
        "is_procedural": True,
    }
    base.update(overrides)
    return CandidateFact.from_dict(base)


def _fake_extractor(payload: list[dict[str, object]]) -> Extractor:
    """Build a fake in-session extractor returning canned JSON — no LLM, no API."""

    def _extract(prompt: str) -> str:
        assert prompt, "extractor must receive the rendered prompt"
        return json.dumps(payload)

    return _extract


# ---- Schema round-trips + validation ----------------------------------------


def test_to_dict_to_json_round_trip() -> None:
    fact = _fact()
    as_dict = fact.to_dict()
    assert CandidateFact.from_dict(as_dict) == fact
    assert CandidateFact.from_dict(json.loads(fact.to_json())) == fact


def test_from_dict_rejects_non_object() -> None:
    with pytest.raises(CandidateValidationError):
        CandidateFact.from_dict(["not", "an", "object"])


def test_from_dict_rejects_missing_field() -> None:
    data = _fact().to_dict()
    del data["confidence"]
    with pytest.raises(CandidateValidationError, match="missing field"):
        CandidateFact.from_dict(data)


def test_from_dict_rejects_unknown_field() -> None:
    data = _fact().to_dict()
    data["surprise"] = "boo"
    with pytest.raises(CandidateValidationError, match="unknown field"):
        CandidateFact.from_dict(data)


def test_from_dict_rejects_unknown_enum_type() -> None:
    data = _fact().to_dict()
    data["type"] = "gossip"
    with pytest.raises(CandidateValidationError, match="type"):
        CandidateFact.from_dict(data)


def test_from_dict_rejects_unknown_provenance() -> None:
    data = _fact().to_dict()
    data["provenance"] = "rumor"
    with pytest.raises(CandidateValidationError, match="provenance"):
        CandidateFact.from_dict(data)


def test_from_dict_rejects_unknown_confidence() -> None:
    data = _fact().to_dict()
    data["confidence"] = "very-high"
    with pytest.raises(CandidateValidationError, match="confidence"):
        CandidateFact.from_dict(data)


def test_from_dict_rejects_wrong_typed_is_procedural() -> None:
    data = _fact().to_dict()
    data["is_procedural"] = "yes"
    with pytest.raises(CandidateValidationError, match="is_procedural"):
        CandidateFact.from_dict(data)


def test_parse_candidates_rejects_non_json() -> None:
    with pytest.raises(CandidateValidationError, match="not valid JSON"):
        parse_candidates("{not json")


def test_parse_candidates_rejects_non_list() -> None:
    with pytest.raises(CandidateValidationError, match="must be a JSON list"):
        parse_candidates(json.dumps(_fact().to_dict()))


def test_parse_candidates_happy_path() -> None:
    payload = json.dumps([_fact().to_dict(), _fact(type="reference").to_dict()])
    facts = parse_candidates(payload)
    assert [f.type for f in facts] == ["feedback", "reference"]


# ---- Prompt asset -----------------------------------------------------------


def test_prompt_is_versioned() -> None:
    assert EXTRACTION_PROMPT_VERSION


def test_prompt_states_required_instructions() -> None:
    text = EXTRACTION_PROMPT.lower()
    assert "future" in text  # only future-relevant durable facts
    assert "trigger" in text and "failure" in text  # procedural lessons
    assert "git" in text  # omit repo/git-recoverable
    assert "claude.md" in text  # omit CLAUDE.md restatements
    assert "when in doubt" in text  # omit-on-doubt


def test_build_prompt_embeds_transcript() -> None:
    rendered = build_extraction_prompt("USER:\nhello\n\nASSISTANT:\nhi")
    assert "USER:\nhello" in rendered
    assert "Transcript follows" in rendered


# ---- Signal gate (§7) -------------------------------------------------------


def test_signal_gate_drops_empty_description() -> None:
    kept = signal_gate([_fact(description="   ")])
    assert kept == []


def test_signal_gate_drops_duplicate_descriptions() -> None:
    first = _fact(body="first body")
    # Same description as `first` but with case/whitespace noise — normalized away.
    dup = _fact(
        body="second body",
        description="  Merged GS migrations are NOT auto-applied to prod  ",
    )
    assert dup.description != first.description  # differ only by case/whitespace
    kept = signal_gate([first, dup])
    assert len(kept) == 1
    assert kept[0].body == "first body"


def test_signal_gate_drops_low_confidence_single_mention() -> None:
    noise = _fact(
        description="maybe the cache is slow on tuesdays",
        confidence="low",
        provenance="claude-inferred",
    )
    kept = signal_gate([noise])
    assert kept == []


def test_signal_gate_keeps_low_confidence_nathan_stated() -> None:
    # nathan-stated is never dropped as uncorroborated noise even at low confidence.
    fact = _fact(confidence="low", provenance="nathan-stated")
    kept = signal_gate([fact])
    assert kept == [fact]


def test_signal_gate_keeps_high_confidence() -> None:
    fact = _fact(confidence="high", provenance="claude-inferred")
    kept = signal_gate([fact])
    assert kept == [fact]


def test_signal_gate_keeps_distinct_facts() -> None:
    a = _fact(description="rule about migrations")
    b = _fact(description="rule about worktrees")
    kept = signal_gate([a, b])
    assert len(kept) == 2


# ---- Privacy filter (§8) — OBVIOUSLY-FAKE seeded secrets only ----------------


def test_privacy_filter_blocks_seeded_postgres_url() -> None:
    leak = _fact(
        description="connection string for the fake db",
        body="postgresql://fakeuser:FAKEPASS123@fake-host.example/neondb?sslmode=require",
    )
    assert privacy_filter([leak]) == []


def test_privacy_filter_blocks_seeded_database_url_var() -> None:
    leak = _fact(body="set NEON_DATABASE_URL to the value Nathan pasted")
    assert privacy_filter([leak]) == []


def test_privacy_filter_blocks_seeded_anthropic_key() -> None:
    leak = _fact(body="key is sk-ant-FAKE000000000000000000notreal")
    assert privacy_filter([leak]) == []


def test_privacy_filter_blocks_seeded_github_token() -> None:
    leak = _fact(body="token ghp_FAKE000000000000000000000000notreal")
    assert privacy_filter([leak]) == []


def test_privacy_filter_blocks_seeded_token_assignment() -> None:
    leak = _fact(body='CORRECTION_EXPORT_TOKEN="FAKEtoken-not-real-1234"')
    assert privacy_filter([leak]) == []


def test_privacy_filter_blocks_secret_in_description() -> None:
    leak = _fact(description="API_KEY=FAKEvalue-not-real-9999 is the prod key")
    assert privacy_filter([leak]) == []


def test_privacy_filter_keeps_clean_fact() -> None:
    clean = _fact()
    assert privacy_filter([clean]) == [clean]


def test_privacy_filter_does_not_redact_only_drops() -> None:
    # A gate, not a scrubber: a dropped fact never reappears redacted.
    leak = _fact(body="postgresql://fakeuser:FAKEPASS@fake-host/db")
    clean = _fact(description="a clean durable fact")
    kept = privacy_filter([leak, clean])
    assert kept == [clean]


# ---- Full pipeline seam against a FAKE extractor -----------------------------


def test_extract_candidates_full_pipeline() -> None:
    payload = [
        _fact(description="durable rule one").to_dict(),
        # duplicate of one -> dropped by signal gate
        _fact(description="durable rule one", body="dup body").to_dict(),
        # low-confidence single-mention -> dropped by signal gate
        _fact(
            description="flaky single mention",
            confidence="low",
            provenance="claude-inferred",
        ).to_dict(),
        # seeded secret -> dropped by privacy filter
        _fact(
            description="leaked creds",
            body="postgresql://fakeuser:FAKEPASS@fake-host/db",
        ).to_dict(),
    ]
    result = extract_candidates("USER:\nhi", extractor=_fake_extractor(payload))
    assert [f.description for f in result] == ["durable rule one"]


def test_extract_candidates_passes_prompt_to_extractor() -> None:
    captured: dict[str, str] = {}

    def _extractor(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps([_fact().to_dict()])

    extract_candidates("USER:\nthe transcript text", extractor=_extractor)
    assert "the transcript text" in captured["prompt"]
    assert "Transcript follows" in captured["prompt"]


def test_extract_candidates_propagates_validation_error() -> None:
    def _bad_extractor(prompt: str) -> str:
        return "this is not json"

    with pytest.raises(CandidateValidationError):
        extract_candidates("USER:\nhi", extractor=_bad_extractor)


def test_extract_candidates_empty_list() -> None:
    result = extract_candidates("USER:\nhi", extractor=_fake_extractor([]))
    assert result == []
