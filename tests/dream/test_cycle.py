# ABOUTME: Tests for the dream-cycle convergent runner glue — unprocessed enumeration, enqueue/drain,
# ABOUTME: gate+prefilter worksheets, verdict apply, finalize. Fakes for the LLM seams; temp dirs/repos only.

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from oversteward.dream import cycle
from oversteward.dream.consolidate import Band, FlaggedItem, MemoryFile, MemoryStore, flagged_key
from oversteward.dream.extract import CandidateFact
from oversteward.dream.ledger import ProcessedLedger, transcript_hash


# ---- helpers ----------------------------------------------------------------


def _candidate_dict(**overrides: object) -> dict:
    base = {
        "type": "feedback",
        "description": "merged GS migrations are not auto-applied to prod",
        "body": "Check alembic_version vs head and migrate-before-promote.",
        "provenance": "claude-inferred",
        "confidence": "high",
        "is_procedural": True,
    }
    base.update(overrides)
    return base


def _memory(
    name: str, description: str, *, body: str = "Original.\n", provenance: str = "claude-inferred"
) -> MemoryFile:
    return MemoryFile(
        name=name,
        description=description,
        metadata={
            "type": "feedback",
            "provenance": provenance,
            "created": "2026-01-01",
            "last_reinforced": "2026-01-01",
            "confidence": "high",
            "decay_status": "active",
            "source_sessions": ["sess-old"],
        },
        body=body,
        filename=f"{name}.md",
    )


def _write_transcript(projects_root: Path, project: str, session_id: str, body: str) -> Path:
    project_dir = projects_root / project
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    path.write_text(body, encoding="utf-8")
    return path


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)


# ---- find_unprocessed -------------------------------------------------------


def test_find_unprocessed_filters_ledger(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    older = _write_transcript(root, "-home-natha-oversteward", "aaa", "first")
    newer = _write_transcript(root, "-home-natha-oversteward", "bbb", "second")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    ledger.record("aaa", transcript_hash(older), older)

    pending = cycle.find_unprocessed(root, ledger)
    assert [p.session_id for p in pending] == ["bbb"]
    assert pending[0].repo == "oversteward"
    assert pending[0].content_hash == transcript_hash(newer)


def test_find_unprocessed_oldest_first(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    older = _write_transcript(root, "-home-natha-oversteward", "old", "x")
    newer = _write_transcript(root, "-home-natha-oversteward", "new", "y")
    os.utime(older, (1000, 1000))
    os.utime(newer, (5000, 5000))
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    pending = cycle.find_unprocessed(root, ledger)
    assert [p.session_id for p in pending] == ["old", "new"]


def test_find_unprocessed_repo_filter(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    _write_transcript(root, "-home-natha-oversteward", "os1", "x")
    _write_transcript(root, "-home-natha-grantspider", "gs1", "y")
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    pending = cycle.find_unprocessed(root, ledger, repo="oversteward")
    assert [p.session_id for p in pending] == ["os1"]


def test_pending_transcript_roundtrips() -> None:
    p = cycle.PendingTranscript("s", "/path.jsonl", "oversteward", "deadbeef")
    assert cycle.PendingTranscript.from_dict(p.to_dict()) == p


# ---- enqueue / drain (Stop-hook idempotency) --------------------------------


def test_enqueue_new_transcript(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    assert cycle.enqueue_transcript(
        queue, ledger, session_id="s1", path="/t.jsonl", content_hash="h1"
    )
    assert queue.read_text().count("\n") == 1


def test_enqueue_idempotent_against_queue(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    cycle.enqueue_transcript(queue, ledger, session_id="s1", path="/t.jsonl", content_hash="h1")
    assert (
        cycle.enqueue_transcript(queue, ledger, session_id="s1", path="/t.jsonl", content_hash="h1")
        is False
    )
    assert queue.read_text().count("\n") == 1


def test_enqueue_skips_already_processed(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("bytes")
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    h = transcript_hash(transcript)
    ledger.record("s1", h, transcript)
    assert (
        cycle.enqueue_transcript(queue, ledger, session_id="s1", path=str(transcript), content_hash=h)
        is False
    )
    assert queue.exists() is False


def test_pending_queue_count_and_drain(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    cycle.enqueue_transcript(queue, ledger, session_id="s1", path="/a.jsonl", content_hash="h1")
    cycle.enqueue_transcript(queue, ledger, session_id="s2", path="/b.jsonl", content_hash="h2")
    assert cycle.pending_queue_count(queue, ledger) == 2
    # h1 gets processed → drain removes it.
    ledger.record("s1", "h1", Path("/a.jsonl"))
    assert cycle.drain_queue(queue, ledger) == 1
    assert cycle.pending_queue_count(queue, ledger) == 1


# ---- build_worksheets (gate + privacy + prefilter) --------------------------


def test_build_worksheets_gates_and_ranks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("close", "merged migrations not auto-applied to prod"))
    store.write(_memory("far", "telegram operator disconnect heuristics"))
    raw = json.dumps(
        [
            _candidate_dict(description="merged migrations not auto-applied to prod"),
            _candidate_dict(
                description="a leaked secret",
                body="export NEON_DATABASE_URL=postgres://u:p@host/db",
            ),
        ]
    )
    sheets = cycle.build_worksheets(raw, store, top_k=10)
    # The secret candidate is dropped by the privacy filter.
    assert len(sheets) == 1
    assert sheets[0].prefiltered[0].filename == "close.md"


def test_build_worksheets_to_dict_shape(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("m1", "something close"))
    raw = json.dumps([_candidate_dict(description="something close")])
    sheet = cycle.build_worksheets(raw, store)[0]
    d = sheet.to_dict()
    assert d["candidate"]["description"] == "something close"
    assert d["prefiltered"][0] == {"filename": "m1.md", "description": "something close"}


# ---- apply_verdicts ---------------------------------------------------------


def test_apply_appends_on_low_similarity(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [(cand, cycle.Verdict(similarity=0.1))],
        store,
        today=date(2026, 6, 27),
        session_id="sess-x",
    )
    assert outcomes[0].action == Band.APPEND
    assert len(store.memories()) == 1
    assert cycle.collect_written_paths(store, outcomes)[0].name.endswith(".md")


def test_apply_merges_on_match(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("feedback_x", "merged migrations", body="Old.\n"))
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [
            (
                cand,
                cycle.Verdict(
                    similarity=0.95, match_filename="feedback_x.md", merged_body="Refined.\n"
                ),
            )
        ],
        store,
        today=date(2026, 6, 27),
    )
    assert outcomes[0].action == Band.AUTO_MERGE
    assert store.memories()[0].body.strip() == "Refined."


def test_apply_auto_appends_ambiguous(tmp_path: Path) -> None:
    # Ambiguous 0.55-0.85 is auto-approved now (OS#134): apply appends a new file
    # rather than collecting a flag.
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("feedback_x", "merged migrations", body="Untouched.\n"))
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [(cand, cycle.Verdict(similarity=0.7, match_filename="feedback_x.md"))],
        store,
        today=date(2026, 6, 27),
    )
    assert outcomes[0].action == Band.APPEND
    assert cycle.collect_flagged(outcomes) == []
    assert len(store.memories()) == 2


def test_apply_holds_nathan_stated_contradiction(tmp_path: Path) -> None:
    # The only thing apply still flags: a contradiction against a nathan-stated law.
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("feedback_law", "nathan law", body="Law.\n", provenance="nathan-stated"))
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [(cand, cycle.Verdict(similarity=0.95, match_filename="feedback_law.md", is_contradiction=True))],
        store,
        today=date(2026, 6, 27),
    )
    assert outcomes[0].action == Band.FLAG
    flagged = cycle.collect_flagged(outcomes)
    assert len(flagged) == 1
    assert flagged[0].nearest is not None and flagged[0].nearest.filename == "feedback_law.md"
    assert [m.filename for m in store.memories()] == ["feedback_law.md"]


def test_verdict_roundtrips() -> None:
    v = cycle.Verdict(0.9, match_filename="x.md", merged_body="b", is_contradiction=True)
    assert cycle.Verdict.from_dict(v.to_dict()) == v


# ---- flagged (de)serialization for the CLI shuttle --------------------------


def test_flagged_roundtrip_preserves_render_fields(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.write(_memory("feedback_x", "near", provenance="nathan-stated"))
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [(cand, cycle.Verdict(similarity=0.95, match_filename="feedback_x.md", is_contradiction=True))],
        store,
        today=date(2026, 6, 27),
    )
    item = cycle.collect_flagged(outcomes)[0]
    restored = cycle.flagged_from_dict(cycle.flagged_to_dict(item))
    assert restored.candidate.description == item.candidate.description
    assert restored.reason == item.reason
    assert restored.similarity == item.similarity
    assert restored.nearest is not None and restored.nearest.filename == "feedback_x.md"


# ---- finalize ---------------------------------------------------------------


def test_default_commit_message_has_skip_ci_marker() -> None:
    msg = cycle.default_commit_message([cycle.PendingTranscript("s", "/p", "oversteward", "h")])
    assert cycle.SKIP_CI_MARKER in msg
    assert "1 session" in msg


def test_finalize_writes_index_review_commits_and_records(tmp_path: Path) -> None:
    repo = tmp_path / "steward-memory"
    repo.mkdir()
    _init_git_repo(repo)
    store = MemoryStore(repo / "memory")
    cand = CandidateFact.from_dict(_candidate_dict())
    outcomes = cycle.apply_verdicts(
        [(cand, cycle.Verdict(similarity=0.1))], store, today=date(2026, 6, 27), session_id="s1"
    )
    written = cycle.collect_written_paths(store, outcomes)
    flagged = cycle.collect_flagged(outcomes)
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("bytes")
    processed = [
        cycle.PendingTranscript("s1", str(transcript), "oversteward", transcript_hash(transcript))
    ]
    result = cycle.finalize_run(
        store,
        cycle.RunResults(flagged=flagged, written_paths=written, processed=processed),
        ledger,
        cycle.FinalizeOptions(repo_root=repo, now=datetime(2026, 6, 27, tzinfo=timezone.utc)),
    )
    assert result.index_path.name == "MEMORY.md"
    assert result.review_path.name == "MEMORY_REVIEW.md"
    assert result.commit.committed is True
    assert cycle.SKIP_CI_MARKER in result.commit.message
    assert result.recorded == ["s1"]
    # The recorded transcript is now idempotently skipped.
    assert ledger.is_processed(transcript_hash(transcript)) is True
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, check=True, capture_output=True, text=True
    )
    assert "dream: consolidate memory" in log.stdout


def test_finalize_records_even_with_no_facts(tmp_path: Path) -> None:
    repo = tmp_path / "steward-memory"
    repo.mkdir()
    _init_git_repo(repo)
    store = MemoryStore(repo / "memory")
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("bytes")
    processed = [
        cycle.PendingTranscript("s1", str(transcript), "oversteward", transcript_hash(transcript))
    ]
    # repo_root omitted → defaults to the store's parent (the steward-memory repo).
    result = cycle.finalize_run(store, cycle.RunResults(processed=processed), ledger)
    # No facts → still records the transcript so it is not re-processed.
    assert result.recorded == ["s1"]


# ---- durable open set (OS#134 Bug 1) ----------------------------------------


def _flagged_item(description: str, *, nearest: str | None = "feedback_law.md") -> FlaggedItem:
    near = _memory(Path(nearest).stem, "law", provenance="nathan-stated") if nearest else None
    return FlaggedItem(
        candidate=CandidateFact.from_dict(_candidate_dict(description=description)),
        reason="contradicts a nathan-stated memory — surfaced, never auto-written",
        similarity=0.95,
        nearest=near,
    )


def test_flagged_store_merge_dedupes_and_accumulates(tmp_path: Path) -> None:
    fs = cycle.FlaggedStore(tmp_path / "flagged.jsonl")
    a = _flagged_item("hold A")
    b = _flagged_item("hold B")
    fs.merge([a])
    full = fs.merge([b])
    assert {i.candidate.description for i in full} == {"hold A", "hold B"}
    # Re-surfacing A collapses onto its key — no duplicate.
    again = fs.merge([a])
    assert len(again) == 2


def test_flagged_store_drain_all_and_by_key(tmp_path: Path) -> None:
    fs = cycle.FlaggedStore(tmp_path / "flagged.jsonl")
    a = _flagged_item("hold A")
    b = _flagged_item("hold B")
    fs.merge([a, b])
    # Drain one by key.
    removed = fs.drain([flagged_key(a)])
    assert removed == 1
    assert [i.candidate.description for i in fs.open_items()] == ["hold B"]
    # Drain the rest (no keys → all).
    assert fs.drain() == 1
    assert fs.open_items() == []


def test_finalize_preserves_prior_flags_on_barren_run(tmp_path: Path) -> None:
    # Acceptance #4: two back-to-back finalize_run calls. Run 1 holds an item; a
    # second consecutive run with ZERO flags must NOT wipe it.
    repo = tmp_path / "steward-memory"
    repo.mkdir()
    _init_git_repo(repo)
    store = MemoryStore(repo / "memory")
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    opts = cycle.FinalizeOptions(repo_root=repo, flagged_path=tmp_path / "flagged.jsonl")

    held = _flagged_item("a held contradiction")
    run1 = cycle.finalize_run(store, cycle.RunResults(flagged=[held]), ledger, opts)
    assert run1.open_flagged == 1
    assert "a held contradiction" in run1.review_path.read_text(encoding="utf-8")

    # Run 2: zero flags. The prior hold survives — the consecutive-run clobber is gone.
    run2 = cycle.finalize_run(store, cycle.RunResults(flagged=[]), ledger, opts)
    assert run2.open_flagged == 1
    assert "a held contradiction" in run2.review_path.read_text(encoding="utf-8")


def test_finalize_accumulates_flags_across_runs(tmp_path: Path) -> None:
    repo = tmp_path / "steward-memory"
    repo.mkdir()
    _init_git_repo(repo)
    store = MemoryStore(repo / "memory")
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    opts = cycle.FinalizeOptions(repo_root=repo, flagged_path=tmp_path / "flagged.jsonl")

    cycle.finalize_run(store, cycle.RunResults(flagged=[_flagged_item("hold A")]), ledger, opts)
    run2 = cycle.finalize_run(
        store, cycle.RunResults(flagged=[_flagged_item("hold B")]), ledger, opts
    )
    assert run2.open_flagged == 2
    text = run2.review_path.read_text(encoding="utf-8")
    assert "hold A" in text and "hold B" in text


def test_drain_flagged_clears_open_set_and_rebuilds_surface(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    fs = cycle.FlaggedStore(tmp_path / "flagged.jsonl")
    fs.merge([_flagged_item("hold A"), _flagged_item("hold B")])
    result = cycle.drain_flagged(store, fs)
    assert result.drained == 2
    assert result.remaining == 0
    text = result.review_path.read_text(encoding="utf-8")
    assert "hold A" not in text and "hold B" not in text


# ---- Stop hook (subprocess: enqueue + fail-open) ----------------------------


_HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "dream_stop_reminder.py"


def _run_hook(event: dict, env: dict) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env}
    return subprocess.run(
        ["python3", str(_HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_stop_hook_enqueues_ending_session(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("session bytes")
    env = {"OVERSTEWARD_DREAM_QUEUE": str(queue), "OVERSTEWARD_DREAM_LEDGER": str(ledger)}
    proc = _run_hook({"session_id": "s1", "transcript_path": str(transcript)}, env)
    assert proc.returncode == 0
    assert queue.is_file()
    assert queue.read_text().count("\n") == 1
    # Second stop of the same transcript is idempotent.
    proc2 = _run_hook({"session_id": "s1", "transcript_path": str(transcript)}, env)
    assert proc2.returncode == 0
    assert queue.read_text().count("\n") == 1


def test_stop_hook_fails_open_on_garbage(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    env = {"OVERSTEWARD_DREAM_QUEUE": str(queue), "OVERSTEWARD_DREAM_LEDGER": str(ledger)}
    proc = subprocess.run(
        ["python3", str(_HOOK)],
        input="not json at all",
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )
    assert proc.returncode == 0


def test_stop_hook_never_blocks_when_transcript_missing(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    env = {"OVERSTEWARD_DREAM_QUEUE": str(queue), "OVERSTEWARD_DREAM_LEDGER": str(ledger)}
    proc = _run_hook({"session_id": "s1", "transcript_path": str(tmp_path / "nope.jsonl")}, env)
    assert proc.returncode == 0
