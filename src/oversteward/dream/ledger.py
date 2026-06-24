# ABOUTME: Append-only processed-transcript ledger for dream-cycle idempotency.
# ABOUTME: Records which transcripts were consolidated (by content hash) so re-runs don't double-process.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class LedgerEntry:
    """One recorded consolidation. Keyed for idempotency by ``content_hash``."""

    session_id: str
    content_hash: str
    path: str
    processed_at: str


def default_ledger_path(repo_root: Path) -> Path:
    """Factory for the repo-tracked ledger location. Git-tracked = the audit trail."""
    return repo_root / "data" / "dream" / "processed_transcripts.jsonl"


def transcript_hash(path: Path) -> str:
    """Stable content hash of a transcript file. Re-runs over the same bytes match."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProcessedLedger:
    """Append-only JSONL record of processed transcripts.

    Idempotency key is the transcript's content hash: a transcript that grows
    (the session continued) hashes differently and is treated as unprocessed,
    while re-running over identical bytes is a no-op. The backing file is created
    lazily on first record and survives restarts (it is read back on construction
    of any later instance pointing at the same path).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._hashes: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content_hash = record.get("content_hash")
                if isinstance(content_hash, str):
                    self._hashes.add(content_hash)

    def is_processed(self, content_hash: str) -> bool:
        """True if a transcript with this content hash was already recorded."""
        return content_hash in self._hashes

    def record(
        self,
        session_id: str,
        content_hash: str,
        path: Path,
        now: datetime | None = None,
    ) -> bool:
        """Append a processed entry. Returns False (no-op) if already recorded.

        The append is atomic per line; the in-memory hash set keeps repeated calls
        within one process cheap and idempotent.
        """
        if content_hash in self._hashes:
            return False
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        entry = LedgerEntry(
            session_id=session_id,
            content_hash=content_hash,
            path=str(path),
            processed_at=timestamp,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.__dict__, sort_keys=True) + "\n")
        self._hashes.add(content_hash)
        return True
