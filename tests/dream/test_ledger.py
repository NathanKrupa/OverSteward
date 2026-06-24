# ABOUTME: Tests for the append-only processed-transcript ledger (idempotency + persistence).
# ABOUTME: Uses a tmp_path ledger file; never reads or writes the real data/dream ledger.

from __future__ import annotations

from pathlib import Path

from oversteward.dream.ledger import ProcessedLedger, transcript_hash


def _transcript(tmp_path: Path, body: str = "session bytes") -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text(body)
    return path


def test_record_then_processed(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path)
    ledger = ProcessedLedger(tmp_path / "ledger.jsonl")
    h = transcript_hash(transcript)
    assert ledger.is_processed(h) is False
    assert ledger.record("s1", h, transcript) is True
    assert ledger.is_processed(h) is True


def test_record_is_idempotent(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path)
    ledger_path = tmp_path / "ledger.jsonl"
    ledger = ProcessedLedger(ledger_path)
    h = transcript_hash(transcript)
    assert ledger.record("s1", h, transcript) is True
    # Processing the same transcript again is a no-op.
    assert ledger.record("s1", h, transcript) is False
    assert ledger_path.read_text().count("\n") == 1


def test_persists_across_instances(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path)
    ledger_path = tmp_path / "ledger.jsonl"
    h = transcript_hash(transcript)
    ProcessedLedger(ledger_path).record("s1", h, transcript)
    # A fresh instance (simulating a restart) reads back the prior record.
    reloaded = ProcessedLedger(ledger_path)
    assert reloaded.is_processed(h) is True
    assert reloaded.record("s1", h, transcript) is False


def test_changed_content_is_unprocessed(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    transcript = _transcript(tmp_path, "first")
    ledger = ProcessedLedger(ledger_path)
    ledger.record("s1", transcript_hash(transcript), transcript)
    # The session continued and the file grew → new hash → treated as unprocessed.
    transcript.write_text("first and more")
    assert ledger.is_processed(transcript_hash(transcript)) is False


def test_creates_ledger_lazily(tmp_path: Path) -> None:
    ledger_path = tmp_path / "nested" / "ledger.jsonl"
    transcript = _transcript(tmp_path)
    ledger = ProcessedLedger(ledger_path)
    assert ledger_path.exists() is False
    ledger.record("s1", transcript_hash(transcript), transcript)
    assert ledger_path.is_file() is True
