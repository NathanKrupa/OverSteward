# ABOUTME: Read-only enumeration and parsing of Claude Code session transcripts.
# ABOUTME: Middle layer — discovers *.jsonl under ~/.claude/projects/* and renders role-tagged text.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Project dirs are keyed by dash-encoded CWD. A worktree's CWD lives under the
# repo's own .claude/worktrees/, so its project dir is the repo dir name with a
# "--claude-worktrees-<name>" suffix. We split on this marker to recover the repo.
_WORKTREE_MARKER = "--claude-worktrees-"


@dataclass(frozen=True)
class TranscriptMeta:
    """Metadata for one discovered session transcript. No transcript body."""

    session_id: str
    path: Path
    project_dir: str
    repo: str
    mtime: float
    is_worktree: bool


def default_projects_root() -> Path:
    """Factory for the real projects directory. The only place the real path lives."""
    return Path.home() / ".claude" / "projects"


def infer_repo(project_dir_name: str) -> str:
    """Recover the repo name from a dash-encoded project-dir name.

    ``-home-natha-grantspider`` → ``grantspider``.
    ``-home-natha-grantspider--claude-worktrees-foo`` → ``grantspider``.
    The leading dash and path segments are encoded as dashes, so the repo is the
    final path segment of the CWD — the last dash-delimited token before any
    worktree marker.
    """
    base = project_dir_name.split(_WORKTREE_MARKER, 1)[0]
    return base.rsplit("-", 1)[-1]


def _session_id(path: Path) -> str:
    """The session id is the transcript filename without its .jsonl suffix."""
    return path.stem


def _scan_project_dir(project_dir: Path) -> list[TranscriptMeta]:
    """Collect transcript metadata for every ``*.jsonl`` in one project dir."""
    dir_name = project_dir.name
    is_worktree = _WORKTREE_MARKER in dir_name
    repo = infer_repo(dir_name)
    metas: list[TranscriptMeta] = []
    for path in sorted(project_dir.glob("*.jsonl")):
        if not path.is_file():
            continue
        metas.append(
            TranscriptMeta(
                session_id=_session_id(path),
                path=path,
                project_dir=dir_name,
                repo=repo,
                mtime=path.stat().st_mtime,
                is_worktree=is_worktree,
            )
        )
    return metas


def enumerate_transcripts(projects_root: Path) -> list[TranscriptMeta]:
    """Discover every ``*.jsonl`` session under ``projects_root/<project-dir>/``.

    Read-only. Includes worktree-derived project dirs (a repo's chats split across
    its main dir and per-worktree dirs). Returns metadata sorted newest-first by
    mtime. A missing or non-directory root yields an empty list — never an error.
    """
    if not projects_root.is_dir():
        return []
    metas: list[TranscriptMeta] = []
    for project_dir in sorted(projects_root.iterdir()):
        if project_dir.is_dir():
            metas.extend(_scan_project_dir(project_dir))
    metas.sort(key=lambda m: m.mtime, reverse=True)
    return metas


def find_transcript(projects_root: Path, session_id: str) -> TranscriptMeta | None:
    """Return the transcript metadata for ``session_id``, or None if not found."""
    for meta in enumerate_transcripts(projects_root):
        if meta.session_id == session_id:
            return meta
    return None


def read_records(path: Path) -> list[dict[str, Any]]:
    """Parse a .jsonl transcript into a list of records, skipping malformed lines.

    Claude Code transcripts occasionally contain a partially-flushed final line;
    a malformed line is skipped rather than aborting the whole read.
    """
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _render_blocks(content: Any) -> list[str]:
    """Render a message ``content`` field (str or list of blocks) to text lines.

    Strips tool-call noise to what's useful for later fact extraction: keeps text
    and thinking prose, summarizes tool calls and their results to one line each.
    """
    if isinstance(content, str):
        text = content.strip()
        return [text] if text else []
    if not isinstance(content, list):
        return []
    lines: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        line = _render_block(block)
        if line:
            lines.append(line)
    return lines


def _render_block(block: dict[str, Any]) -> str:
    """Render one content block to a single text fragment, or '' to drop it."""
    block_type = block.get("type")
    if block_type in ("text", "thinking"):
        text = str(block.get(block_type, "")).strip()
        return text
    if block_type == "tool_use":
        return f"[tool_use: {block.get('name', '?')}]"
    if block_type == "tool_result":
        return "[tool_result]"
    return ""


def parse_transcript(path: Path) -> str:
    """Read a ``.jsonl`` session and return a clean, role-tagged text view.

    Read-only. Each user/assistant message becomes a ``ROLE:`` headed block with
    tool-call noise collapsed to one-line markers. Non-message records (mode,
    attachment, ai-title, etc.) are dropped — they carry no extraction signal.
    """
    sections: list[str] = []
    for record in read_records(path):
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        body = "\n".join(_render_blocks(message.get("content")))
        if not body.strip():
            continue
        sections.append(f"{role.upper()}:\n{body}")
    return "\n\n".join(sections)
