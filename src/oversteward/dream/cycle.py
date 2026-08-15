# ABOUTME: Deterministic batch glue for the convergent dream cycle — enumerate, gate+prefilter, apply, finalize.
# ABOUTME: The /dream skill drives the in-session LLM seams (extract, judge) and calls these MIDDLE-layer steps.

"""The convergent dream-cycle runner's deterministic steps (design §4, §11).

All three triggers — sign-off, the Stop-hook enqueue, the cron backstop — converge
on the ``/dream`` skill, which is orchestration ONLY: an in-session Claude reads
each transcript, does extraction and judging on the Max subscription (the §14-3
seams), and between those steps calls the helpers here for everything
deterministic:

- :func:`find_unprocessed` — transcripts whose hash is not in the ledger (step 1).
- :func:`build_worksheets` — gate + privacy + Jaccard prefilter, the judge's
  worksheet (steps 2-3), reusing :mod:`oversteward.dream.extract` /
  :mod:`oversteward.dream.consolidate` — no consolidation logic is duplicated.
- :func:`apply_verdicts` — feed each in-session verdict through the existing
  :func:`~oversteward.dream.consolidate.consolidate` write ops (step 3).
- :func:`finalize_run` — index regen, review surface, doc-only commit, ledger
  record (step 4, batched once per run).

The pending-queue helpers (:func:`enqueue_transcript` etc.) are re-exported from
:mod:`oversteward.dream.ledger` so the stdlib-only Stop hook and this module share
one implementation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from .consolidate import (
    DEFAULT_STORE_PATH,
    CommitResult,
    ConsolidationOutcome,
    FlaggedItem,
    Judge,
    JudgeResult,
    MemoryFile,
    MemoryStore,
    commit_store,
    consolidate,
    flagged_key,
    jaccard_prefilter,
)
from .extract import CandidateFact, parse_candidates, privacy_filter, signal_gate
from .ledger import (
    DEFAULT_QUEUE_PATH,
    ProcessedLedger,
    default_ledger_path,
    drain_queue,
    enqueue_transcript,
    pending_queue_count,
    queued_hashes,
    transcript_hash,
)
from .transcripts import default_projects_root, enumerate_transcripts

__all__ = [
    "DEFAULT_QUEUE_PATH",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_STORE_PATH",
    "DEFAULT_STORE_REPO",
    "FLAGGED_FILENAME",
    "SKIP_CI_MARKER",
    "DrainResult",
    "FinalizeOptions",
    "FinalizeResult",
    "FlaggedStore",
    "PendingTranscript",
    "RunResults",
    "Verdict",
    "Worksheet",
    "apply_verdicts",
    "build_worksheets",
    "collect_flagged",
    "collect_written_paths",
    "default_commit_message",
    "drain_flagged",
    "drain_queue",
    "enqueue_transcript",
    "find_unprocessed",
    "finalize_run",
    "flagged_from_dict",
    "flagged_key",
    "flagged_to_dict",
    "gate_candidates",
    "pending_queue_count",
    "queued_hashes",
]

# The OverSteward repo root (this file is src/oversteward/dream/cycle.py).
OVERSTEWARD_ROOT = Path(__file__).resolve().parents[3]

# Defaults wiring the live operator/cron run. The memory STORE is the private
# steward-memory repo (design §14-1); the LEDGER is OverSteward's data/dream
# idempotency record (component b). Both are injectable everywhere below.
DEFAULT_STORE_REPO = DEFAULT_STORE_PATH.parent
DEFAULT_LEDGER_PATH = default_ledger_path(OVERSTEWARD_ROOT)

# The cycle's only writes are Markdown — a doc-only commit that skips CI (HARD
# CONSTRAINT #2 / acceptance #5).
_COMMIT_PREFIX = "dream: consolidate memory"
SKIP_CI_MARKER = "[skip ci]"

# The durable open set of held flagged items, a per-machine JSONL sibling of the
# ledger (OS#134). The review surface is rebuilt from this full set each run so a
# barren cycle never wipes prior holds; items leave only via an explicit drain.
FLAGGED_FILENAME = "flagged.jsonl"
_FLAGGED_KEY = "key"

# Serialization keys shared across the JSON-shuttle (de)serializers.
_CANDIDATE = "candidate"
_SIMILARITY = "similarity"


# ---- step 1: enumerate unprocessed ------------------------------------------


@dataclass(frozen=True)
class PendingTranscript:
    """One transcript awaiting consolidation (not yet in the ledger)."""

    session_id: str
    path: str
    repo: str
    content_hash: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PendingTranscript:
        return cls(
            session_id=data["session_id"],
            path=data["path"],
            repo=data["repo"],
            content_hash=data["content_hash"],
        )


def find_unprocessed(
    projects_root: Path, ledger: ProcessedLedger, *, repo: str | None = None
) -> list[PendingTranscript]:
    """Transcripts under ``projects_root`` whose content hash is not in ``ledger``.

    Returned oldest-first so consolidation builds memory chronologically (a later
    session reinforces an earlier fact). Optionally filtered to one ``repo``
    (Phase 1 may run OverSteward-only, design §14-7). A no-op run — nothing
    unprocessed — yields an empty list, the skill's "ledger current" early exit.
    """
    pending: list[PendingTranscript] = []
    for meta in reversed(enumerate_transcripts(projects_root)):
        if repo is not None and meta.repo != repo:
            continue
        content_hash = transcript_hash(meta.path)
        if ledger.is_processed(content_hash):
            continue
        pending.append(
            PendingTranscript(
                session_id=meta.session_id,
                path=str(meta.path),
                repo=meta.repo,
                content_hash=content_hash,
            )
        )
    return pending


# ---- steps 2-3: gate + prefilter worksheet ----------------------------------


def gate_candidates(raw_extractor_output: str) -> list[CandidateFact]:
    """Validate + gate + privacy-filter the in-session extractor's raw JSON output.

    Composes the existing :mod:`oversteward.dream.extract` deterministic steps
    (the extraction LLM call already happened in-session); no logic is duplicated.
    """
    candidates = parse_candidates(raw_extractor_output)
    candidates = signal_gate(candidates)
    return privacy_filter(candidates)


@dataclass
class Worksheet:
    """One surviving candidate plus the prefiltered existing memories to judge it against."""

    candidate: CandidateFact
    prefiltered: list[MemoryFile]

    def to_dict(self) -> dict:
        return {
            _CANDIDATE: self.candidate.to_dict(),
            "prefiltered": [
                {"filename": mem.filename, "description": mem.description}
                for mem in self.prefiltered
            ],
        }


def build_worksheets(
    raw_extractor_output: str, store: MemoryStore, *, top_k: int = 10
) -> list[Worksheet]:
    """Gate the raw candidates, then attach each one's top-K Jaccard-nearest memories.

    The output is what the in-session judge reads: the surviving candidate plus the
    short existing-memory descriptions to score it against (§6 prefilter bounds the
    judge call). Secrets and noise are already dropped by :func:`gate_candidates`.
    """
    candidates = gate_candidates(raw_extractor_output)
    memories = store.memories()
    return [
        Worksheet(candidate=cand, prefiltered=jaccard_prefilter(cand, memories, top_k=top_k))
        for cand in candidates
    ]


# ---- step 3: apply verdicts -------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The in-session judge's verdict for one candidate (the §14-3 seam's output).

    ``match_filename`` names the existing memory the judge matched (resolved back
    to the live store object at apply time), so the verdict survives the JSON
    shuttle between the skill's CLI calls.
    """

    similarity: float
    match_filename: str | None = None
    merged_body: str | None = None
    is_contradiction: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Verdict:
        return cls(
            similarity=float(data[_SIMILARITY]),
            match_filename=data.get("match_filename"),
            merged_body=data.get("merged_body"),
            is_contradiction=bool(data.get("is_contradiction", False)),
        )


def _by_filename(memories: list[MemoryFile], filename: str) -> MemoryFile | None:
    for mem in memories:
        if mem.filename == filename:
            return mem
    return None


def _verdict_judge(store: MemoryStore, verdict: Verdict) -> Judge:
    """Wrap a decided verdict as a :data:`~oversteward.dream.consolidate.Judge`.

    The in-session model already judged; this adapter lets the existing
    :func:`consolidate` write pipeline run unchanged (acceptance #4). The matched
    memory is resolved from the live store so an auto-merge mutates the on-disk
    object :func:`consolidate` will write.
    """

    def judge(candidate: CandidateFact, prefiltered: list[MemoryFile]) -> JudgeResult:
        match: MemoryFile | None = None
        if verdict.match_filename is not None:
            match = _by_filename(prefiltered, verdict.match_filename) or _by_filename(
                store.memories(), verdict.match_filename
            )
        return JudgeResult(
            similarity=verdict.similarity,
            match=match,
            merged_body=verdict.merged_body,
            is_contradiction=verdict.is_contradiction,
        )

    return judge


def apply_verdicts(
    judged: list[tuple[CandidateFact, Verdict]],
    store: MemoryStore,
    *,
    today: date,
    session_id: str | None = None,
) -> list[ConsolidationOutcome]:
    """Route each judged candidate through :func:`consolidate` against ``store``.

    Processed sequentially so a freshly-appended file is visible to the next
    candidate's prefilter. Returns the per-candidate outcomes; the caller batches
    :func:`collect_flagged` / :func:`collect_written_paths` for finalize.
    """
    return [
        consolidate(
            candidate,
            store,
            judge=_verdict_judge(store, verdict),
            today=today,
            session_id=session_id,
        )
        for candidate, verdict in judged
    ]


def collect_flagged(outcomes: list[ConsolidationOutcome]) -> list[FlaggedItem]:
    """The flagged items from a batch of outcomes (the review-surface input)."""
    return [outcome.flagged for outcome in outcomes if outcome.flagged is not None]


def collect_written_paths(
    store: MemoryStore, outcomes: list[ConsolidationOutcome]
) -> list[Path]:
    """Deduplicated store paths a batch wrote/merged (the commit's pathspec)."""
    seen: set[Path] = set()
    paths: list[Path] = []
    for outcome in outcomes:
        if outcome.written is None:
            continue
        path = store.root / outcome.written.filename
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


# ---- flagged (de)serialization for the skill's JSON shuttle -----------------


def flagged_to_dict(item: FlaggedItem) -> dict:
    """Serialize a flagged item to the minimum the review surface renders."""
    return {
        _CANDIDATE: item.candidate.to_dict(),
        "reason": item.reason,
        _SIMILARITY: item.similarity,
        "nearest_filename": item.nearest.filename if item.nearest is not None else None,
    }


def flagged_from_dict(data: dict) -> FlaggedItem:
    """Rebuild a flagged item from :func:`flagged_to_dict` (nearest as a stub file)."""
    nearest_filename = data.get("nearest_filename")
    nearest: MemoryFile | None = None
    if nearest_filename:
        nearest = MemoryFile(
            name=Path(nearest_filename).stem,
            description="",
            metadata={},
            body="",
            filename=nearest_filename,
        )
    return FlaggedItem(
        candidate=CandidateFact.from_dict(data[_CANDIDATE]),
        reason=data["reason"],
        similarity=data[_SIMILARITY],
        nearest=nearest,
    )


# ---- durable open set (OS#134 Bug 1) ----------------------------------------


def default_flagged_path(ledger: ProcessedLedger) -> Path:
    """The flagged open set's path — a JSONL sibling of the ledger."""
    return ledger.path.parent / FLAGGED_FILENAME


class FlaggedStore:
    """The durable, keyed open set of held flagged items, persisted as JSONL.

    The review surface is rebuilt from the **full** set each run (OS#134 Bug 1):
    :meth:`merge` folds a run's new holds in, de-duped by :func:`flagged_key`, and
    :meth:`drain` is the explicit approve/clear operation. A barren run merges
    nothing and the prior open set survives — the consecutive-run clobber is gone.
    Each line is ``{"key": <key>, ...flagged_to_dict(item)}``; the key makes both
    de-dup and selective drain self-describing.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _records(self) -> list[dict]:
        if not self._path.is_file():
            return []
        records: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
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

    def _write(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
        self._path.write_text(text, encoding="utf-8")

    def open_items(self) -> list[FlaggedItem]:
        """Every held item currently in the open set, in insertion order."""
        return [flagged_from_dict(record) for record in self._records()]

    def merge(self, items: list[FlaggedItem]) -> list[FlaggedItem]:
        """Fold ``items`` into the open set (de-duped by key); return the full set.

        Existing entries are preserved and re-surfaced holds collapse onto their
        key rather than duplicating, so the set only ever grows by genuinely new
        holds. The full open set is returned for the caller to render.
        """
        by_key: dict[str, dict] = {}
        for record in self._records():
            key = record.get(_FLAGGED_KEY)
            if isinstance(key, str):
                by_key[key] = record
        for item in items:
            key = flagged_key(item)
            by_key[key] = {_FLAGGED_KEY: key, **flagged_to_dict(item)}
        ordered = list(by_key.values())
        self._write(ordered)
        return [flagged_from_dict(record) for record in ordered]

    def drain(self, keys: list[str] | None = None) -> int:
        """Clear approved holds — all of them, or only the named ``keys``.

        Returns the number removed. This is the explicit approve/drain operation
        the open-set model needs: a hold leaves the set only here, never by a
        later run silently overwriting the surface.
        """
        records = self._records()
        if keys is None:
            kept: list[dict] = []
        else:
            wanted = set(keys)
            kept = [record for record in records if record.get(_FLAGGED_KEY) not in wanted]
        removed = len(records) - len(kept)
        self._write(kept)
        return removed


@dataclass
class DrainResult:
    """What a drain did — items cleared, the rebuilt surface, the remaining count."""

    drained: int
    review_path: Path
    remaining: int


def drain_flagged(
    store: MemoryStore,
    flagged_store: FlaggedStore,
    *,
    keys: list[str] | None = None,
) -> DrainResult:
    """Approve/clear holds, then rebuild ``MEMORY_REVIEW.md`` from what remains.

    Clears the named ``keys`` (or ALL when ``keys`` is None) from the open set and
    regenerates the review surface from the survivors — the explicit drain the
    open-set model needs (OS#134). Does NOT commit; the caller batches the
    store-repo commit, matching :func:`finalize_run`'s split.
    """
    drained = flagged_store.drain(keys)
    remaining = flagged_store.open_items()
    review_path = store.write_review_surface(remaining)
    return DrainResult(drained=drained, review_path=review_path, remaining=len(remaining))


# ---- step 4: finalize (batched once per run) --------------------------------


def default_commit_message(processed: list[PendingTranscript]) -> str:
    """The doc-only, CI-skipping commit message for a cycle (acceptance #5)."""
    count = len(processed)
    plural = "" if count == 1 else "s"
    return f"{_COMMIT_PREFIX} ({count} session{plural}) {SKIP_CI_MARKER}"


@dataclass
class RunResults:
    """The batch outputs one cycle accumulated across transcripts, ready to finalize.

    Mirrors the JSON the skill assembles between ``apply`` and ``finalize`` (each
    transcript's flagged items + written paths, plus the processed-transcript list).
    """

    flagged: list[FlaggedItem] = field(default_factory=list)
    written_paths: list[Path] = field(default_factory=list)
    processed: list[PendingTranscript] = field(default_factory=list)


@dataclass
class FinalizeResult:
    """What the once-per-run finalize did — index, review, commit, ledger, queue."""

    index_path: Path
    review_path: Path
    commit: CommitResult
    recorded: list[str] = field(default_factory=list)
    queue_drained: int = 0
    open_flagged: int = 0


def _record_processed(
    ledger: ProcessedLedger, processed: list[PendingTranscript], now: datetime | None
) -> list[str]:
    """Record every processed transcript (even barren ones); return new session ids."""
    return [
        transcript.session_id
        for transcript in processed
        if ledger.record(
            transcript.session_id, transcript.content_hash, Path(transcript.path), now=now
        )
    ]


@dataclass(frozen=True)
class FinalizeOptions:
    """Optional finalize knobs. ``repo_root`` defaults to the store's parent.

    ``flagged_path`` is the durable open set; it defaults to a JSONL sibling of
    the ledger so a test's temp ledger keeps its open set isolated.
    """

    repo_root: Path | None = None
    message: str | None = None
    now: datetime | None = None
    queue_path: Path | None = None
    flagged_path: Path | None = None


def _rebuild_surfaces(
    store: MemoryStore,
    ledger: ProcessedLedger,
    results: RunResults,
    flagged_path: Path | None,
) -> tuple[Path, Path, int]:
    """Regenerate the index and rebuild the review surface from the FULL open set.

    The run's holds are merged into the durable :class:`FlaggedStore` (de-duped by
    key) and the survivors render ``MEMORY_REVIEW.md``, so a barren run can no
    longer wipe prior unreviewed state (OS#134 Bug 1). Returns the index path, the
    review path, and the open-set size.
    """
    index_path = store.regenerate_index()
    path = flagged_path if flagged_path is not None else default_flagged_path(ledger)
    open_set = FlaggedStore(path).merge(results.flagged)
    review_path = store.write_review_surface(open_set)
    return index_path, review_path, len(open_set)


def finalize_run(
    store: MemoryStore,
    results: RunResults,
    ledger: ProcessedLedger,
    options: FinalizeOptions | None = None,
) -> FinalizeResult:
    """Regenerate the index + review surface, commit (doc-only), record the ledger.

    Batched once per cycle (step 4). Each processed transcript is recorded even when
    it yielded no facts, so a barren session is not re-processed next run. The commit
    is the audit trail; the ledger update is local idempotency state. The review
    surface is rebuilt from the full open set (see :func:`_rebuild_surfaces`).
    """
    opts = options or FinalizeOptions()
    repo_root = opts.repo_root if opts.repo_root is not None else store.root.parent
    index_path, review_path, open_flagged = _rebuild_surfaces(
        store, ledger, results, opts.flagged_path
    )
    message = opts.message or default_commit_message(results.processed)
    commit = commit_store(repo_root, [*results.written_paths, index_path, review_path], message)
    drained = drain_queue(opts.queue_path, ledger) if opts.queue_path is not None else 0
    return FinalizeResult(
        index_path=index_path,
        review_path=review_path,
        commit=commit,
        open_flagged=open_flagged,
        recorded=_record_processed(ledger, results.processed, opts.now),
        queue_drained=drained,
    )
