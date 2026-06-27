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
    "SKIP_CI_MARKER",
    "FinalizeOptions",
    "FinalizeResult",
    "PendingTranscript",
    "RunResults",
    "Verdict",
    "Worksheet",
    "apply_verdicts",
    "build_worksheets",
    "collect_flagged",
    "collect_written_paths",
    "default_commit_message",
    "drain_queue",
    "enqueue_transcript",
    "find_unprocessed",
    "finalize_run",
    "flagged_from_dict",
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
    """Optional finalize knobs. ``repo_root`` defaults to the store's parent."""

    repo_root: Path | None = None
    message: str | None = None
    now: datetime | None = None
    queue_path: Path | None = None


def finalize_run(
    store: MemoryStore,
    results: RunResults,
    ledger: ProcessedLedger,
    options: FinalizeOptions | None = None,
) -> FinalizeResult:
    """Regenerate the index + review surface, commit (doc-only), record the ledger.

    Batched once per cycle (step 4). Each processed transcript is recorded even when
    it yielded no facts, so a barren session is not re-processed next run. The commit
    is the audit trail; the ledger update is local idempotency state.
    """
    opts = options or FinalizeOptions()
    repo_root = opts.repo_root if opts.repo_root is not None else store.root.parent
    index_path = store.regenerate_index()
    review_path = store.write_review_surface(results.flagged)
    message = opts.message or default_commit_message(results.processed)
    commit = commit_store(repo_root, [*results.written_paths, index_path, review_path], message)
    drained = drain_queue(opts.queue_path, ledger) if opts.queue_path is not None else 0
    return FinalizeResult(
        index_path=index_path,
        review_path=review_path,
        commit=commit,
        recorded=_record_processed(ledger, results.processed, opts.now),
        queue_drained=drained,
    )
