# ABOUTME: Tests for dream-cycle transcript enumeration and parsing over committed fixtures.
# ABOUTME: Never touches the live ~/.claude/projects dir — builds a fake projects root under tmp_path.

from __future__ import annotations

import shutil
from pathlib import Path

from oversteward.dream.transcripts import (
    enumerate_transcripts,
    find_transcript,
    infer_repo,
    parse_transcript,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample-session.jsonl"


def _make_projects_root(tmp_path: Path) -> Path:
    """Build a fake ~/.claude/projects with a main dir and a worktree-derived dir."""
    root = tmp_path / "projects"
    main_dir = root / "-home-natha-grantspider"
    worktree_dir = root / "-home-natha-grantspider--claude-worktrees-foo"
    main_dir.mkdir(parents=True)
    worktree_dir.mkdir(parents=True)
    shutil.copy(FIXTURE, main_dir / "aaaa-main.jsonl")
    shutil.copy(FIXTURE, worktree_dir / "bbbb-wt.jsonl")
    return root


def test_infer_repo_main_dir() -> None:
    assert infer_repo("-home-natha-grantspider") == "grantspider"


def test_infer_repo_worktree_dir() -> None:
    assert infer_repo("-home-natha-grantspider--claude-worktrees-gov-opp") == "grantspider"


def test_enumerate_discovers_main_and_worktree(tmp_path: Path) -> None:
    root = _make_projects_root(tmp_path)
    metas = enumerate_transcripts(root)
    session_ids = {m.session_id for m in metas}
    assert session_ids == {"aaaa-main", "bbbb-wt"}
    by_id = {m.session_id: m for m in metas}
    assert by_id["aaaa-main"].is_worktree is False
    assert by_id["bbbb-wt"].is_worktree is True
    assert all(m.repo == "grantspider" for m in metas)


def test_enumerate_missing_root_is_empty(tmp_path: Path) -> None:
    assert enumerate_transcripts(tmp_path / "nope") == []


def test_find_transcript(tmp_path: Path) -> None:
    root = _make_projects_root(tmp_path)
    assert find_transcript(root, "aaaa-main").session_id == "aaaa-main"
    assert find_transcript(root, "missing") is None


def test_parse_renders_role_tagged_text() -> None:
    text = parse_transcript(FIXTURE)
    assert "USER:\nPlease summarize the registry." in text
    assert "Reading the registry now." in text
    assert "The user wants a summary." in text  # thinking prose kept
    assert "[tool_use: Read]" in text  # tool call collapsed to a marker
    assert "[tool_result]" in text
    # Noise records (ai-title, mode) and the malformed line are dropped.
    assert "noise record" not in text
    assert "not valid json" not in text


def test_parse_skips_malformed_lines(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n{ broken\n')
    assert parse_transcript(bad) == "USER:\nhi"
