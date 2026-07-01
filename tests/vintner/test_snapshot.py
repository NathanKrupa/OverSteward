# ABOUTME: Tests for the velocity snapshot store — persist/load per-stage counts, tolerate missing/corrupt files.
# ABOUTME: Pure file I/O with an injected path; no DB.

from __future__ import annotations

from oversteward.vintner.snapshot import load_snapshot, save_snapshot


def test_missing_snapshot_is_none(tmp_path):
    assert load_snapshot(tmp_path / "nope.json") is None


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    counts = {"foundations_total": 300_000, "websites_crawled": 36_000}
    save_snapshot(path, counts, "2026-07-01T12:00:00+00:00")
    assert load_snapshot(path) == counts


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "skills" / "pipeline-status" / "state.json"
    save_snapshot(path, {"a": 1}, "2026-07-01T12:00:00+00:00")
    assert path.exists()
    assert load_snapshot(path) == {"a": 1}


def test_corrupt_snapshot_is_none(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_snapshot(path) is None


def test_snapshot_without_counts_key_is_none(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"generated_at": "x"}', encoding="utf-8")
    assert load_snapshot(path) is None


def test_non_int_values_are_dropped(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"counts": {"a": 5, "b": "oops"}}', encoding="utf-8")
    assert load_snapshot(path) == {"a": 5}
