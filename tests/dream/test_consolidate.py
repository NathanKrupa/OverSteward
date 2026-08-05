# ABOUTME: Tests for dream-cycle resolve/dedup + write — prefilter, bands, provenance guard, write ops, index, flag surface, commit.
# ABOUTME: Uses a FAKE judge + a TEMP memory store + a TEMP git repo — NEVER the live steward-memory repo or ~/.claude.

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from oversteward.dream.consolidate import (
    AUTO_MERGE_THRESHOLD,
    FLAG_THRESHOLD,
    FULL_INDEX_FILENAME,
    INDEX_FILENAME,
    REVIEW_FILENAME,
    Band,
    CommitResult,
    ConsolidationOutcome,
    FlaggedItem,
    Judge,
    JudgeResult,
    MemoryFile,
    MemoryParseError,
    MemoryStore,
    classify_band,
    commit_store,
    consolidate,
    flagged_key,
    jaccard_prefilter,
    jaccard_similarity,
)
from oversteward.dream.extract import CandidateFact


def _fact(**overrides: object) -> CandidateFact:
    base = {
        "type": "feedback",
        "description": "merged GS migrations are not auto-applied to prod",
        "body": "Check alembic_version vs head and migrate-before-promote since prod deploys from main.",
        "provenance": "claude-inferred",
        "confidence": "high",
        "is_procedural": True,
    }
    base.update(overrides)
    return CandidateFact.from_dict(base)


def _memory(
    name: str,
    description: str,
    *,
    provenance: str = "claude-inferred",
    body: str = "Original body.\n",
    last_reinforced: str = "2026-01-01",
    sessions: list[str] | None = None,
) -> MemoryFile:
    return MemoryFile(
        name=name,
        description=description,
        metadata={
            "type": "feedback",
            "provenance": provenance,
            "created": "2026-01-01",
            "last_reinforced": last_reinforced,
            "confidence": "high",
            "decay_status": "active",
            "source_sessions": list(sessions or ["sess-old"]),
        },
        body=body,
        filename=f"{name}.md",
    )


def _fake_judge(
    similarity: float,
    *,
    match: MemoryFile | None = None,
    merged_body: str | None = None,
    is_contradiction: bool = False,
) -> Judge:
    """A FAKE in-session judge returning a canned verdict — no LLM, no API."""

    def judge(candidate: CandidateFact, memories: list[MemoryFile]) -> JudgeResult:
        return JudgeResult(
            similarity=similarity,
            match=match,
            merged_body=merged_body,
            is_contradiction=is_contradiction,
        )

    return judge


def _store_with(tmp_path: Path, *memories: MemoryFile) -> MemoryStore:
    store = MemoryStore(tmp_path / "memory")
    for mem in memories:
        store.write(mem)
    return store


# ---- frontmatter parse / render ---------------------------------------------


def test_parse_roundtrips_frontmatter(tmp_path: Path) -> None:
    mem = _memory("ref_x", "a recall hook")
    store = _store_with(tmp_path, mem)
    reloaded = store.memories()
    assert len(reloaded) == 1
    got = reloaded[0]
    assert got.name == "ref_x"
    assert got.description == "a recall hook"
    assert got.metadata["provenance"] == "claude-inferred"
    assert got.metadata["type"] == "feedback"
    assert got.body.strip() == "Original body."


def test_parse_rejects_missing_frontmatter() -> None:
    with pytest.raises(MemoryParseError):
        MemoryFile.parse("no frontmatter here\n", "bad.md")


def test_parse_rejects_malformed_yaml() -> None:
    with pytest.raises(MemoryParseError):
        MemoryFile.parse("---\nname: [unterminated\n---\nbody\n", "bad.md")


def test_store_excludes_index_and_review(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _memory("ref_x", "hook"))
    store.regenerate_index()
    store.write_review_surface([])
    names = {m.filename for m in store.memories()}
    assert names == {"ref_x.md"}
    assert INDEX_FILENAME not in names
    assert REVIEW_FILENAME not in names


# ---- Jaccard prefilter -------------------------------------------------------


def test_jaccard_similarity_basic() -> None:
    assert jaccard_similarity("alpha beta", "alpha beta") == 1.0
    assert jaccard_similarity("alpha beta", "gamma delta") == 0.0
    assert jaccard_similarity("", "") == 0.0


def test_prefilter_ranks_by_overlap(tmp_path: Path) -> None:
    close = _memory("close", "merged migrations not auto-applied to prod")
    middle = _memory("middle", "migrations and prod deploys sometimes")
    far = _memory("far", "telegram operator disconnect heuristics")
    cand = _fact(description="merged migrations not auto-applied to prod")
    ranked = jaccard_prefilter(cand, [far, middle, close], top_k=10)
    assert ranked[0].filename == "close.md"
    assert ranked[-1].filename == "far.md"


def test_prefilter_caps_at_top_k(tmp_path: Path) -> None:
    mems = [_memory(f"m{i}", f"shared token number {i}") for i in range(20)]
    cand = _fact(description="shared token here")
    ranked = jaccard_prefilter(cand, mems, top_k=5)
    assert len(ranked) == 5


# ---- band classifier ---------------------------------------------------------


def test_classify_band_boundaries() -> None:
    assert classify_band(AUTO_MERGE_THRESHOLD) == Band.AUTO_MERGE
    assert classify_band(0.90) == Band.AUTO_MERGE
    assert classify_band(FLAG_THRESHOLD) == Band.FLAG
    assert classify_band(0.70) == Band.FLAG
    assert classify_band(0.84) == Band.FLAG
    assert classify_band(0.54) == Band.APPEND
    assert classify_band(0.0) == Band.APPEND


# ---- append (new file) -------------------------------------------------------


def test_low_similarity_appends_new_file(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    cand = _fact()
    outcome = consolidate(
        cand, store, judge=_fake_judge(0.20), today=date(2026, 6, 24), session_id="sess-new"
    )
    assert outcome.action == Band.APPEND
    assert outcome.written is not None
    written = store.memories()
    assert len(written) == 1
    new = written[0]
    assert new.metadata["type"] == "feedback"
    assert new.metadata["provenance"] == "claude-inferred"
    assert new.metadata["created"] == "2026-06-24"
    assert new.metadata["last_reinforced"] == "2026-06-24"
    assert new.metadata["confidence"] == "high"
    assert new.metadata["decay_status"] == "active"
    assert new.metadata["source_sessions"] == ["sess-new"]
    assert new.description == cand.description


def test_new_file_frontmatter_is_parseable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    consolidate(_fact(), store, judge=_fake_judge(0.1), today=date(2026, 6, 24))
    path = next((store.root).glob("feedback_*.md"))
    # Re-parse from disk — proves the written frontmatter is valid YAML.
    reparsed = MemoryFile.parse(path.read_text(encoding="utf-8"), path.name)
    assert reparsed.metadata["decay_status"] == "active"


def test_append_dedupes_slug(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    cand = _fact(description="same hook")
    consolidate(cand, store, judge=_fake_judge(0.1), today=date(2026, 6, 24))
    consolidate(cand, store, judge=_fake_judge(0.1), today=date(2026, 6, 24))
    names = sorted(m.filename for m in store.memories())
    assert len(names) == 2
    assert names[0] != names[1]


# ---- auto-merge --------------------------------------------------------------


def test_high_similarity_merges_and_bumps(tmp_path: Path) -> None:
    existing = _memory(
        "feedback_x", "merged migrations", last_reinforced="2026-01-01", sessions=["sess-old"]
    )
    store = _store_with(tmp_path, existing)
    # Re-read the on-disk instance so the judge points at the same object the
    # store will load during consolidate.
    target = store.memories()[0]
    cand = _fact()
    outcome = consolidate(
        cand,
        store,
        judge=_fake_judge(0.95, match=target, merged_body="Refined merged body.\n"),
        today=date(2026, 6, 24),
        session_id="sess-new",
    )
    assert outcome.action == Band.AUTO_MERGE
    reloaded = store.memories()[0]
    assert reloaded.body.strip() == "Refined merged body."
    assert reloaded.metadata["last_reinforced"] == "2026-06-24"
    assert reloaded.metadata["source_sessions"] == ["sess-old", "sess-new"]


def test_merge_without_merged_body_keeps_existing(tmp_path: Path) -> None:
    existing = _memory("feedback_x", "merged migrations", body="Keep me.\n")
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(), store, judge=_fake_judge(0.9, match=target), today=date(2026, 6, 24)
    )
    assert outcome.action == Band.AUTO_MERGE
    assert store.memories()[0].body.strip() == "Keep me."


# ---- flag band (ambiguous middle) auto-approves (OS#134) ---------------------


def test_ambiguous_band_auto_appends_not_held(tmp_path: Path) -> None:
    # 0.55-0.85 is auto-approved (Nathan's OS#134 ruling): the judge declined to
    # merge, so the candidate is appended as a new file — never held for review.
    existing = _memory("feedback_x", "merged migrations", body="Untouched.\n")
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(), store, judge=_fake_judge(0.70, match=target), today=date(2026, 6, 24)
    )
    assert outcome.action == Band.APPEND
    assert outcome.flagged is None
    assert outcome.written is not None
    # The matched memory is left untouched; a brand-new file is added alongside it.
    mems = store.memories()
    assert len(mems) == 2
    assert {m.filename for m in mems if m.body.strip() == "Untouched."} == {"feedback_x.md"}


def test_flag_band_contradiction_vs_nathan_stated_still_held(tmp_path: Path) -> None:
    # A flag-band contradiction against a nathan-stated law must be surfaced, not
    # silently auto-appended (acceptance #3): the guard now fires below auto-merge.
    existing = _memory(
        "feedback_law", "durable nathan law", provenance="nathan-stated", body="Nathan's law.\n"
    )
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(),
        store,
        judge=_fake_judge(0.70, match=target, is_contradiction=True),
        today=date(2026, 6, 24),
    )
    assert outcome.action == Band.FLAG
    assert outcome.flagged is not None
    # Nothing written: the law stands alone, no contradicting file appended.
    assert [m.filename for m in store.memories()] == ["feedback_law.md"]


# ---- provenance guard --------------------------------------------------------


def test_contradiction_vs_nathan_stated_flags_not_overwrites(tmp_path: Path) -> None:
    existing = _memory(
        "feedback_law", "durable nathan law", provenance="nathan-stated", body="Nathan's law.\n"
    )
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(provenance="claude-inferred"),
        store,
        judge=_fake_judge(0.95, match=target, merged_body="OVERWRITE", is_contradiction=True),
        today=date(2026, 6, 24),
    )
    assert outcome.action == Band.FLAG
    # The nathan-stated memory is NOT overwritten.
    assert store.memories()[0].body.strip() == "Nathan's law."


def test_contradiction_vs_claude_inferred_high_still_merges(tmp_path: Path) -> None:
    existing = _memory("feedback_x", "inferred thing", provenance="claude-inferred")
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(),
        store,
        judge=_fake_judge(0.95, match=target, merged_body="Corrected.\n", is_contradiction=True),
        today=date(2026, 6, 24),
    )
    # Guard only protects nathan-stated facts; an inferred one may be corrected.
    assert outcome.action == Band.AUTO_MERGE
    assert store.memories()[0].body.strip() == "Corrected."


# ---- index regen -------------------------------------------------------------


def test_full_index_has_one_line_per_memory(tmp_path: Path) -> None:
    store = _store_with(
        tmp_path,
        _memory("a_mem", "first hook"),
        _memory("b_mem", "second hook"),
    )
    path = store.regenerate_index()
    assert path.name == INDEX_FILENAME
    # The full flat index (every recall hook) lives on-demand alongside MEMORY.md.
    full = (store.root / FULL_INDEX_FILENAME).read_text(encoding="utf-8")
    entries = [ln for ln in full.splitlines() if ln.startswith("- [")]
    assert len(entries) == 2
    assert "- [a_mem.md](a_mem.md) — first hook" in entries
    assert "- [b_mem.md](b_mem.md) — second hook" in entries


def test_full_index_carries_a_digest_the_description_lacks(tmp_path: Path) -> None:
    # THE OS#287 recall case: the standing layer renders the digest and no longer
    # carries a file link, so a digest absent from the description would leave that
    # fact unresolvable. The full index carries it (uncapped — the bytes are free).
    mem = _memory("law_x", "a long recall hook", provenance="nathan-stated")
    mem.metadata["digest"] = "short imperative form"
    store = _store_with(tmp_path, mem)
    store.regenerate_index()
    standing = (store.root / INDEX_FILENAME).read_text(encoding="utf-8")
    full = (store.root / FULL_INDEX_FILENAME).read_text(encoding="utf-8")
    # The standing layer states the digest, with no link to resolve it by.
    assert "- short imperative form" in standing
    assert "law_x.md" not in standing
    # Grepping that same text in the full index reaches the file.
    assert "- [law_x.md](law_x.md) — a long recall hook — standing: short imperative form" in full


def test_full_index_does_not_repeat_a_digest_already_in_the_description(
    tmp_path: Path,
) -> None:
    mem = _memory("law_y", "always ship migrations in their own PR", provenance="nathan-stated")
    mem.metadata["digest"] = "always ship migrations"
    store = _store_with(tmp_path, mem)
    store.regenerate_index()
    full = (store.root / FULL_INDEX_FILENAME).read_text(encoding="utf-8")
    assert "standing:" not in full


def test_regenerate_index_emits_standing_orders(tmp_path: Path) -> None:
    # A nathan-stated law surfaces under ## Laws; a plain claude-inferred
    # reference stays non-standing (full index only), not promoted.
    store = _store_with(
        tmp_path,
        _memory("user_law", "always ship migrations in their own PR", provenance="nathan-stated"),
        _memory("ref_plain", "a plain reference fact", provenance="claude-inferred"),
    )
    store.regenerate_index()
    standing = (store.root / INDEX_FILENAME).read_text(encoding="utf-8")
    assert "# Standing Orders" in standing
    assert "## Laws" in standing
    assert "- always ship migrations in their own PR" in standing
    # The keyword-laden-but-inferred reference is NOT a law and NOT standing.
    assert "a plain reference fact" not in standing
    # The recall hook it dropped still resolves via the full index (OS#287).
    full = (store.root / FULL_INDEX_FILENAME).read_text(encoding="utf-8")
    assert "- [user_law.md](user_law.md) — always ship migrations in their own PR" in full


# ---- flag surface ------------------------------------------------------------


def test_review_surface_written(tmp_path: Path) -> None:
    existing = _memory("feedback_x", "near thing", provenance="nathan-stated")
    store = _store_with(tmp_path, existing)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(),
        store,
        judge=_fake_judge(0.95, match=target, is_contradiction=True),
        today=date(2026, 6, 24),
    )
    assert outcome.flagged is not None
    path = store.write_review_surface([outcome.flagged])
    assert path.name == REVIEW_FILENAME
    text = path.read_text(encoding="utf-8")
    assert outcome.candidate.description in text
    assert "feedback_x.md" in text
    assert "0.95" in text
    assert f"**key:** {flagged_key(outcome.flagged)}" in text


def test_flagged_key_stable_and_distinguishes_nearest(tmp_path: Path) -> None:
    law = _memory("feedback_law", "a law", provenance="nathan-stated")
    store = _store_with(tmp_path, law)
    target = store.memories()[0]
    outcome = consolidate(
        _fact(), store, judge=_fake_judge(0.95, match=target, is_contradiction=True),
        today=date(2026, 6, 24),
    )
    assert outcome.flagged is not None
    # The key is deterministic for the same hold and differs when the nearest does.
    assert flagged_key(outcome.flagged) == flagged_key(outcome.flagged)
    other = FlaggedItem(
        candidate=outcome.flagged.candidate, reason="r", similarity=0.95, nearest=None
    )
    assert flagged_key(other) != flagged_key(outcome.flagged)


# ---- commit wrapper ----------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def test_commit_wrapper_commits_changes(tmp_path: Path) -> None:
    repo = tmp_path / "store"
    repo.mkdir()
    _init_git_repo(repo)
    target = repo / "memory" / "feedback_x.md"
    target.parent.mkdir(parents=True)
    target.write_text("content\n", encoding="utf-8")
    result = commit_store(repo, [target], "dream: add feedback_x")
    assert isinstance(result, CommitResult)
    assert result.committed is True
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True
    )
    assert "dream: add feedback_x" in log.stdout


def test_commit_wrapper_noop_when_nothing_changed(tmp_path: Path) -> None:
    repo = tmp_path / "store"
    repo.mkdir()
    _init_git_repo(repo)
    target = repo / "feedback_x.md"
    target.write_text("content\n", encoding="utf-8")
    commit_store(repo, [target], "first")
    # Second commit with no changes is a clean no-op, not an error.
    result = commit_store(repo, [target], "second")
    assert result.committed is False


def test_commit_wrapper_accepts_relative_paths(tmp_path: Path) -> None:
    repo = tmp_path / "store"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "a.md").write_text("a\n", encoding="utf-8")
    result = commit_store(repo, [Path("a.md")], "rel path")
    assert result.committed is True


# ---- outcome shape -----------------------------------------------------------


def test_outcome_is_returned_for_each_action(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    outcome = consolidate(_fact(), store, judge=_fake_judge(0.1), today=date(2026, 6, 24))
    assert isinstance(outcome, ConsolidationOutcome)
    assert outcome.candidate.description == _fact().description
    assert outcome.similarity == 0.1
