# ABOUTME: Resolve/dedup + write the dream cycle — routes CandidateFacts into the memory store by §6 bands.
# ABOUTME: Deterministic scaffolding (Jaccard prefilter, band classifier, write ops, index regen, commit) around an INJECTED judge.

"""The heart of the dream-cycle loop (design §6, §11 steps 4-5).

A :class:`~oversteward.dream.extract.CandidateFact` (from component c) is resolved
against the existing per-file Markdown memory store, then written / merged /
flagged / appended, after which the ``MEMORY.md`` index is regenerated. This
module owns everything *deterministic* around the consolidation step and NOTHING
of the model judgment itself:

- :class:`MemoryFile` / :class:`MemoryStore` — the §3 per-file store, frontmatter
  parsed/written, index + flag surface regenerated. The store path is INJECTABLE
  (default :data:`DEFAULT_STORE_PATH`); nothing tests exercise hardcodes the live
  path.
- :func:`jaccard_prefilter` — §6 token-overlap prefilter bounding the judge's
  work to the top-K most-similar existing memories.
- :data:`Judge` / :class:`JudgeResult` — the INJECTED seam (§14-3). The judge is
  the in-session Max model step scoring similarity + proposing merged text; this
  module never constructs an API client.
- :func:`classify_band` — the §6 band classifier (≥0.85 / 0.55-0.85 / <0.55).
- :func:`consolidate` — the orchestrator wiring prefilter → judge → band → write.
  Per Nathan's ruling (OS#134) the ambiguous 0.55-0.85 band is **auto-approved**
  (appended as a new file), not held; only the provenance guard still surfaces a
  candidate that contradicts a ``nathan-stated`` memory (surfaced, never written).
- :func:`commit_store` — a thin ``git add``/``commit`` wrapper over the store
  repo (injectable path) — the audit trail.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

import yaml

from .extract import CandidateFact

log = logging.getLogger(__name__)

# The git-tracked source-of-truth memory store (design §3 / §14-1). Injectable
# everywhere; this default is referenced only by operator-run code paths, never
# baked into anything a test exercises.
DEFAULT_STORE_PATH = Path("/home/natha/steward-memory/memory")

# §6 band thresholds.
AUTO_MERGE_THRESHOLD = 0.85
FLAG_THRESHOLD = 0.55

# The index + review-surface filenames at the store root.
INDEX_FILENAME = "MEMORY.md"
REVIEW_FILENAME = "MEMORY_REVIEW.md"
# The full flat index — every fact's recall hook, kept on-demand (OS#203) so the
# always-loaded MEMORY.md can be the lean standing-orders layer instead.
FULL_INDEX_FILENAME = "MEMORY_FULL.md"

# Root-level files that are NOT facts (the index + the flag surface) — excluded
# from the fact set when the store enumerates ``*.md``.
_NON_FACT_FILES = frozenset({INDEX_FILENAME, REVIEW_FILENAME, FULL_INDEX_FILENAME})

# §3 frontmatter key names + git invocation tokens, named once each.
_SOURCE_SESSIONS = "source_sessions"
_GIT = "git"
_PATHSPEC_SEP = "--"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---- §3 store ----------------------------------------------------------------


@dataclass
class MemoryFile:
    """One on-disk memory, mirroring the §3 extended frontmatter shape.

    ``name`` is the slug (and the ``<slug>.md`` filename stem); ``description`` is
    the one-line recall hook the judge compares against; ``metadata`` carries the
    §3 typed fields. ``body`` is the Markdown after the frontmatter. ``filename``
    is the basename it was read from (or will be written to).
    """

    name: str
    description: str
    metadata: dict[str, Any]
    body: str
    filename: str

    @classmethod
    def parse(cls, text: str, filename: str) -> MemoryFile:
        """Parse a memory file's text (frontmatter + body) into a value object.

        Raises :class:`MemoryParseError` when the YAML frontmatter block is
        missing or malformed — the store is trusted to *exist*, not to be
        well-formed, so a bad file is surfaced rather than silently skipped.
        """
        match = _FRONTMATTER_RE.match(text)
        if match is None:
            raise MemoryParseError(f"{filename}: no YAML frontmatter block found")
        try:
            front = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise MemoryParseError(f"{filename}: invalid frontmatter YAML: {exc}") from exc
        if not isinstance(front, dict):
            raise MemoryParseError(f"{filename}: frontmatter is not a mapping")
        metadata = front.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise MemoryParseError(f"{filename}: metadata is not a mapping")
        return cls(
            name=str(front.get("name", Path(filename).stem)),
            description=str(front.get("description", "")),
            metadata=metadata,
            body=match.group(2),
            filename=filename,
        )

    def render(self) -> str:
        """Serialize back to frontmatter + body text, ready to write to disk."""
        front = {"name": self.name, "description": self.description, "metadata": self.metadata}
        dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n")
        body = self.body if self.body.endswith("\n") or not self.body else self.body
        return f"---\n{dumped}\n---\n\n{body.lstrip(chr(10))}"

    def provenance(self) -> str | None:
        """The §3 ``metadata.provenance`` value, or None if unset."""
        value = self.metadata.get("provenance")
        return str(value) if value is not None else None


class MemoryParseError(ValueError):
    """A memory file's frontmatter could not be parsed."""


class MemoryStore:
    """The §3 per-file Markdown memory store at an INJECTABLE root path.

    Owns reading every ``<slug>.md`` (the index + review surface are excluded
    from the fact set), writing new files, updating existing ones, regenerating
    the lean ``MEMORY.md`` index, and writing the ``MEMORY_REVIEW.md`` flag
    surface. The root is created lazily on first write.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def memories(self) -> list[MemoryFile]:
        """Parse every fact file in the store (index, review surface, sidecars excluded).

        ``*.steward-variant.md`` sidecars (OS#195 reconciler backups) are NOT live
        facts, so they are skipped from enumeration entirely.
        """
        from .standing import is_steward_variant

        if not self._root.is_dir():
            return []
        out: list[MemoryFile] = []
        for path in sorted(self._root.glob("*.md")):
            if path.name in _NON_FACT_FILES or is_steward_variant(path.name):
                continue
            out.append(MemoryFile.parse(path.read_text(encoding="utf-8"), path.name))
        return out

    def write(self, memory: MemoryFile) -> Path:
        """Write (or overwrite) one memory file, returning its path."""
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / memory.filename
        path.write_text(memory.render(), encoding="utf-8")
        return path

    def regenerate_index(self) -> Path:
        """Rewrite the always-loaded ``MEMORY.md`` as grouped Standing Orders (OS#203).

        ``MEMORY.md`` becomes the lean standing layer — Laws / Habits / Graveyard
        / Living-doc pointers, derived by the strict classifier in
        :mod:`oversteward.dream.standing` (a keyword hit NEVER promotes to law).
        The full flat ``- [file] — desc`` index is preserved in
        :data:`FULL_INDEX_FILENAME` so every fact keeps its recall hook. Sidecar
        variants are already excluded from :meth:`memories`. Returns the
        ``MEMORY.md`` path (the always-loaded layer).
        """
        from .standing import render_standing_orders

        memories = self.memories()
        self._root.mkdir(parents=True, exist_ok=True)
        self._write_full_index(memories)
        path = self._root / INDEX_FILENAME
        path.write_text(render_standing_orders(memories), encoding="utf-8")
        return path

    def _write_full_index(self, memories: list[MemoryFile]) -> Path:
        """Write the on-demand full flat index — one line per fact (OS#203).

        This index owns every fact's recall hook: the standing layer states the
        orders and carries no file links (OS#287), so a fact is resolved to its
        file by grepping its text here. A line therefore also carries the standing
        ``digest`` whenever that text is not already in the description — otherwise
        the digest-bearing facts would be the ones recall could not resolve. The
        index is on-demand and uncapped, so those bytes cost nothing.
        """
        from .standing import standing_text

        lines = ["# Memory Index (full)", ""]
        for mem in memories:
            line = f"- [{mem.filename}]({mem.filename}) — {mem.description}"
            standing = standing_text(mem)
            if standing not in mem.description:
                line = f"{line} — standing: {standing}"
            lines.append(line)
        path = self._root / FULL_INDEX_FILENAME
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_review_surface(self, flagged: list[FlaggedItem]) -> Path:
        """Write ``MEMORY_REVIEW.md`` from the full open set of held candidates.

        The cycle auto-approves the ambiguous 0.55-0.85 band, so the only items
        that land here are candidates the provenance guard held — a contradiction
        against a ``nathan-stated`` memory (surfaced, never auto-written). The
        caller passes the **full accumulated open set** (not just the current
        run's holds), so a barren run never wipes prior state; items leave the set
        only via an explicit drain. One section per held candidate, each carrying
        its dedupe ``key`` for selective drain.
        """
        lines = [
            "# Memory Review Queue",
            "",
            "Held candidates the dream cycle surfaced instead of auto-writing — each",
            "contradicts a `nathan-stated` memory (the provenance guard). Auto-approved",
            "writes land directly in the store (their git history is the audit trail);",
            "only these holds accumulate here across runs until cleared by an explicit",
            "drain (`scripts/dream.py cycle drain`).",
            "",
        ]
        for item in flagged:
            lines.extend(_render_flag(item))
        text = "\n".join(lines).rstrip("\n") + "\n"
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / REVIEW_FILENAME
        path.write_text(text, encoding="utf-8")
        return path


def _render_flag(item: FlaggedItem) -> list[str]:
    cand = item.candidate
    nearest = item.nearest.filename if item.nearest is not None else "(none)"
    return [
        f"## {cand.description}",
        "",
        f"- **key:** {flagged_key(item)}",
        f"- **reason:** {item.reason}",
        f"- **type:** {cand.type}",
        f"- **provenance:** {cand.provenance}",
        f"- **similarity:** {item.similarity:.2f}",
        f"- **nearest existing:** {nearest}",
        "",
        cand.body,
        "",
    ]


# ---- §6 Jaccard prefilter ----------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """Token-set Jaccard overlap of two strings — 0.0 when both are empty."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def jaccard_prefilter(
    candidate: CandidateFact, memories: list[MemoryFile], *, top_k: int = 10
) -> list[MemoryFile]:
    """Rank ``memories`` by description token-overlap with ``candidate``, top-K.

    A cheap deterministic prefilter (§6) bounding how many existing memories the
    injected judge must score — the per-file structure makes this an N-way short
    string comparison. Ties break on filename for determinism; memories with zero
    overlap are still rankable but sort last.
    """
    scored = [
        (jaccard_similarity(candidate.description, mem.description), mem.filename, mem)
        for mem in memories
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [mem for _, _, mem in scored[:top_k]]


# ---- §14-3 injected judge seam ----------------------------------------------


@dataclass(frozen=True)
class JudgeResult:
    """The injected judge's verdict for a candidate against the prefiltered set.

    ``similarity`` is the top similarity (0-1) the judge assigns; ``match`` is the
    existing memory it matched (None when nothing is close); ``merged_body`` is
    the judge's proposed refined body for an auto-merge; ``is_contradiction``
    marks that the candidate *contradicts* the matched memory rather than
    reinforcing it (drives the §6 provenance guard).
    """

    similarity: float
    match: MemoryFile | None = None
    merged_body: str | None = None
    is_contradiction: bool = False


# A ``Judge`` is the in-session Max model step (§14-3): given the candidate and
# the prefiltered existing memories, it returns a :class:`JudgeResult`. Injected
# by the caller and wired to the session model; this module never builds a client.
Judge = Callable[[CandidateFact, list[MemoryFile]], JudgeResult]


# ---- §6 band classifier ------------------------------------------------------


class Band:
    """The three §6 routing bands (string constants, not an enum, for lean JSON)."""

    AUTO_MERGE = "auto-merge"
    FLAG = "flag"
    APPEND = "append"


def classify_band(similarity: float) -> str:
    """Route a similarity score to its §6 band.

    ``>= 0.85`` auto-merge, ``0.55-0.85`` flag (never silent-merge the ambiguous
    middle), ``< 0.55`` append as a new file.
    """
    if similarity >= AUTO_MERGE_THRESHOLD:
        return Band.AUTO_MERGE
    if similarity >= FLAG_THRESHOLD:
        return Band.FLAG
    return Band.APPEND


# ---- Outcomes ----------------------------------------------------------------


@dataclass
class FlaggedItem:
    """A candidate held for human adjudication (§14-5)."""

    candidate: CandidateFact
    reason: str
    similarity: float
    nearest: MemoryFile | None


def flagged_key(item: FlaggedItem) -> str:
    """Stable dedupe key for a held item across runs (candidate + nearest).

    The durable open set (OS#134) keys holds so the same contradiction surfaced
    by two consecutive cycles collapses to one entry, and the operator can drain
    a single hold by its key. Derived from the content that identifies the hold —
    the candidate's type + description and the nearest existing memory.
    """
    nearest = item.nearest.filename if item.nearest is not None else ""
    raw = f"{item.candidate.type}\x00{item.candidate.description}\x00{nearest}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ConsolidationOutcome:
    """The result of resolving one candidate — what the loop did and why."""

    action: str
    candidate: CandidateFact
    similarity: float
    written: MemoryFile | None = None
    flagged: FlaggedItem | None = None


@dataclass(frozen=True)
class WriteContext:
    """Per-run write context — the date to stamp and the originating session id.

    Bundles the audit-trail values (`when` for `created`/`last_reinforced`,
    `session_id` for `source_sessions`) so the write ops take one context object
    rather than threading two loose scalars through the band dispatch.
    """

    when: date
    session_id: str | None = None


# ---- §11 step 4-5 orchestrator ----------------------------------------------


def consolidate(
    candidate: CandidateFact,
    store: MemoryStore,
    *,
    judge: Judge,
    today: date | None = None,
    session_id: str | None = None,
    top_k: int = 10,
) -> ConsolidationOutcome:
    """Resolve one candidate against ``store`` and merge/append/hold (§6, §11).

    The model judgment is INJECTED via ``judge`` (§14-3) — never a hardcoded API
    call. Pipeline: Jaccard prefilter → judge → §6 band → write op. The provenance
    guard runs first: a *contradiction* against a ``nathan-stated`` memory at the
    flag band or above is HELD (surfaced, never auto-written). Otherwise ≥0.85
    auto-merges and everything below auto-appends as a new file — the ambiguous
    0.55-0.85 band is auto-approved (Nathan's OS#134 ruling), no longer held.

    Does NOT regenerate the index or commit — the caller batches those after all
    candidates (the index is rewritten once, the commit is the audit trail for
    the whole run). Use :meth:`MemoryStore.regenerate_index` and
    :func:`commit_store` after consolidating a batch.
    """
    prefiltered = jaccard_prefilter(candidate, store.memories(), top_k=top_k)
    verdict = judge(candidate, prefiltered)
    ctx = WriteContext(when=today or date.today(), session_id=session_id)
    return _route(candidate, store, verdict, ctx)


def _route(
    candidate: CandidateFact,
    store: MemoryStore,
    verdict: JudgeResult,
    ctx: WriteContext,
) -> ConsolidationOutcome:
    """Apply the §6 band + provenance guard to one judged candidate.

    The provenance guard surfaces a ``nathan-stated`` contradiction (held, never
    auto-written). Otherwise the auto-merge band merges and BOTH lower bands
    auto-append: the ambiguous 0.55-0.85 middle is auto-approved (OS#134), no
    longer held for human review.
    """
    band = classify_band(verdict.similarity)
    guard = _provenance_guard(candidate, verdict, band)
    if guard is not None:
        return _flag(candidate, verdict, guard)
    if band == Band.AUTO_MERGE:
        return _merge(candidate, store, verdict, ctx)
    return _append(candidate, store, verdict, ctx)


def _provenance_guard(
    candidate: CandidateFact, verdict: JudgeResult, band: str
) -> str | None:
    """Return a flag reason if the provenance guard trips, else None.

    A contradiction against a matched ``nathan-stated`` memory must be HELD rather
    than written (``feedback_memory_provenance``): an auto-merge would overwrite
    Nathan's law, and — now that the 0.55-0.85 band auto-appends (OS#134) — a
    flag-band contradiction would silently add a contradicting file. The guard
    therefore fires at the flag band and above. The genuinely-unrelated append
    band (<0.55) is ignored: a "contradiction" there is spurious noise.
    """
    if not verdict.is_contradiction or verdict.match is None:
        return None
    if band == Band.APPEND:
        return None
    if verdict.match.provenance() == "nathan-stated":
        return "contradicts a nathan-stated memory — surfaced, never auto-written"
    return None


def _merge(
    candidate: CandidateFact,
    store: MemoryStore,
    verdict: JudgeResult,
    ctx: WriteContext,
) -> ConsolidationOutcome:
    """Refine the matched file's body, bump ``last_reinforced``, append session.

    A candidate's ``superseded_by`` carries onto the match: a retirement arrives as
    a *refinement* of the very fact it retires ("X is gone; use Y"), so the
    auto-merge band is where the graveyard marker is normally earned. Dropping it
    here left facts whose refined body announced their own retirement still
    classified as live law (OS#288). An absent marker never clears an existing one
    — a later reinforcement must not resurrect a retired fact.
    """
    existing = verdict.match
    if existing is None:  # pragma: no cover - guarded by classify_band
        raise ConsolidationError("auto-merge band requires a matched memory")
    existing.body = verdict.merged_body if verdict.merged_body is not None else existing.body
    existing.metadata["last_reinforced"] = ctx.when.isoformat()
    if candidate.superseded_by is not None:
        existing.metadata["superseded_by"] = candidate.superseded_by
    _append_session(existing.metadata, ctx.session_id)
    store.write(existing)
    return ConsolidationOutcome(
        action=Band.AUTO_MERGE,
        candidate=candidate,
        similarity=verdict.similarity,
        written=existing,
    )


def _append(
    candidate: CandidateFact,
    store: MemoryStore,
    verdict: JudgeResult,
    ctx: WriteContext,
) -> ConsolidationOutcome:
    """Write a brand-new ``<slug>.md`` with full §3 frontmatter."""
    memory = _new_memory(candidate, ctx, existing=store.memories())
    store.write(memory)
    return ConsolidationOutcome(
        action=Band.APPEND,
        candidate=candidate,
        similarity=verdict.similarity,
        written=memory,
    )


def _flag(candidate: CandidateFact, verdict: JudgeResult, reason: str) -> ConsolidationOutcome:
    """Hold a candidate for the review surface — never a silent write."""
    item = FlaggedItem(
        candidate=candidate,
        reason=reason,
        similarity=verdict.similarity,
        nearest=verdict.match,
    )
    return ConsolidationOutcome(
        action=Band.FLAG,
        candidate=candidate,
        similarity=verdict.similarity,
        flagged=item,
    )


class ConsolidationError(RuntimeError):
    """An internal invariant of the consolidation pipeline was violated."""


def _new_memory(
    candidate: CandidateFact,
    ctx: WriteContext,
    *,
    existing: list[MemoryFile],
) -> MemoryFile:
    """Build a §3-shaped :class:`MemoryFile` for a new fact, with a unique slug."""
    slug = _unique_slug(candidate, {mem.filename for mem in existing})
    metadata = {
        "type": candidate.type,
        "provenance": candidate.provenance,
        "created": ctx.when.isoformat(),
        "last_reinforced": ctx.when.isoformat(),
        "confidence": candidate.confidence,
        "decay_status": "active",
        _SOURCE_SESSIONS: [ctx.session_id] if ctx.session_id else [],
    }
    _apply_two_axis(metadata, candidate)
    return MemoryFile(
        name=slug,
        description=candidate.description,
        metadata=metadata,
        body=candidate.body.rstrip("\n") + "\n",
        filename=f"{slug}.md",
    )


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    return slug or "memory"


def _unique_slug(candidate: CandidateFact, taken: set[str]) -> str:
    """A filesystem-safe slug from type + description, de-duplicated against ``taken``."""
    base = f"{candidate.type}_{_slugify(candidate.description)}"[:80].rstrip("_")
    slug = base
    suffix = 2
    while f"{slug}.md" in taken:
        slug = f"{base}_{suffix}"
        suffix += 1
    return slug


def _apply_two_axis(metadata: dict[str, Any], candidate: CandidateFact) -> None:
    """Persist the optional dream-written fields (OS#203 two-axis + the graveyard marker).

    ``tier`` / ``scope`` / ``digest`` are stamped into frontmatter only when the
    candidate carries them, so an un-tiered fact keeps a lean metadata block and
    the standing generator derives its tier. An explicit ``tier`` on disk later
    overrides that derivation. ``superseded_by`` (OS#206 follow-up) is the explicit
    graveyard marker — when the supersession path sets it, the standing classifier
    files the retired fact under Graveyard.
    """
    if candidate.tier is not None:
        metadata["tier"] = candidate.tier
    if candidate.scope:
        metadata["scope"] = list(candidate.scope)
    if candidate.digest is not None:
        metadata["digest"] = candidate.digest
    if candidate.superseded_by is not None:
        metadata["superseded_by"] = candidate.superseded_by


def _append_session(metadata: dict[str, Any], session_id: str | None) -> None:
    """Append ``session_id`` to ``metadata.source_sessions`` (created if absent)."""
    if not session_id:
        return
    sessions = metadata.get(_SOURCE_SESSIONS)
    if not isinstance(sessions, list):
        sessions = []
    if session_id not in sessions:
        sessions.append(session_id)
    metadata[_SOURCE_SESSIONS] = sessions


# ---- §11 step 5 commit wrapper ----------------------------------------------


@dataclass
class CommitResult:
    """The outcome of a store commit — the audit trail (§11 step 5)."""

    committed: bool
    message: str
    paths: list[str] = field(default_factory=list)


def commit_store(
    repo_root: Path, paths: list[Path], message: str
) -> CommitResult:
    """Stage ``paths`` and commit them in the store repo at ``repo_root`` (§11 step 5).

    A thin ``git add``/``git commit`` wrapper — the dream cycle's audit trail.
    The repo root is INJECTABLE (tests run it against a temp git repo; the live
    store commit is operator-run). Stages only the given paths (never ``-A``).
    Returns ``committed=False`` with no error when there is nothing to commit, so
    a no-op run does not raise.
    """
    rels = [str(p.relative_to(repo_root)) if p.is_absolute() else str(p) for p in paths]
    subprocess.run([_GIT, "add", _PATHSPEC_SEP, *rels], cwd=repo_root, check=True)
    status = subprocess.run(
        [_GIT, "status", "--porcelain", _PATHSPEC_SEP, *rels],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        log.info("commit_store: nothing staged for %s", rels)
        return CommitResult(committed=False, message=message, paths=rels)
    subprocess.run([_GIT, "commit", "-m", message, _PATHSPEC_SEP, *rels], cwd=repo_root, check=True)
    return CommitResult(committed=True, message=message, paths=rels)
