# ABOUTME: Stdlib-only dream-cycle idempotency state — the processed-transcript ledger and pending queue.
# ABOUTME: Importable by the Stop hook (system python3, no yaml) so re-runs and re-stops don't double-process.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# The Stop hook's lightweight enqueue surface, outside any git repo (machine-local
# runtime state). Overridable; the hook honors OVERSTEWARD_DREAM_QUEUE.
DEFAULT_QUEUE_PATH = Path.home() / ".claude" / "dream_queue.jsonl"

# The idempotency key both JSONL records (ledger + queue) carry.
_CONTENT_HASH = "content_hash"


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


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into dict records, skipping malformed/blank lines.

    A missing file yields an empty list — both the ledger and the queue are created
    lazily, so absence is a normal state, not an error.
    """
    if not path.is_file():
        return []
    records: list[dict] = []
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
        for record in _read_jsonl(self._path):
            content_hash = record.get(_CONTENT_HASH)
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


# ---- pending queue (Stop-hook enqueue surface) ------------------------------


@dataclass(frozen=True)
class QueueEntry:
    """One transcript a Stop hook flagged as awaiting consolidation."""

    session_id: str
    path: str
    content_hash: str
    enqueued_at: str


def queued_hashes(queue_path: Path) -> set[str]:
    """Content hashes currently sitting in the pending queue."""
    return {
        record[_CONTENT_HASH]
        for record in _read_jsonl(queue_path)
        if isinstance(record.get(_CONTENT_HASH), str)
    }


def enqueue_transcript(
    queue_path: Path,
    ledger: ProcessedLedger,
    *,
    session_id: str,
    path: str,
    content_hash: str,
    now: datetime | None = None,
) -> bool:
    """Append a transcript to the pending queue, returning False on a no-op.

    Idempotent against BOTH the ledger (already consolidated → skip) and the queue
    itself (already enqueued → skip), so a Stop hook firing repeatedly over the
    same session bytes never double-enqueues. The queue is created lazily.
    """
    if ledger.is_processed(content_hash):
        return False
    if content_hash in queued_hashes(queue_path):
        return False
    entry = QueueEntry(
        session_id=session_id,
        path=str(path),
        content_hash=content_hash,
        enqueued_at=(now or datetime.now(timezone.utc)).isoformat(),
    )
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.__dict__, sort_keys=True) + "\n")
    return True


def pending_queue_count(queue_path: Path, ledger: ProcessedLedger) -> int:
    """How many queued transcripts are not yet recorded in the ledger."""
    return sum(
        1
        for record in _read_jsonl(queue_path)
        if isinstance(record.get(_CONTENT_HASH), str)
        and not ledger.is_processed(record[_CONTENT_HASH])
    )


def drain_queue(queue_path: Path, ledger: ProcessedLedger) -> int:
    """Drop queue entries whose transcript is now in the ledger; return the count removed."""
    records = _read_jsonl(queue_path)
    kept = [r for r in records if not ledger.is_processed(str(r.get(_CONTENT_HASH, "")))]
    removed = len(records) - len(kept)
    if removed:
        text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in kept)
        queue_path.write_text(text, encoding="utf-8")
    return removed
