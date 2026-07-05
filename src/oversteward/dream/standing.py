# ABOUTME: Strict deterministic classifier + renderer turning per-file memories into grouped Standing Orders.
# ABOUTME: The always-loaded MEMORY.md lean layer (Laws / Habits / Graveyard / Living-doc pointers); keyword gates NEVER promote to law.

"""Standing-orders generation (OS#201/#203 core).

The always-loaded ``MEMORY.md`` used to be a flat ``- [file] — desc`` index of
every fact — 468 lines that grew every session. This module collapses it to a
lean **Standing Orders** layer: four groups (``## Laws``, ``## Habits``,
``## Graveyard``, ``## Living-doc pointers``) driven by a **strict deterministic
classifier**. The full flat index is preserved separately (``MEMORY_FULL.md``) so
no fact loses its recall hook.

THE LOAD-BEARING CONSTRAINT (why this issue exists): a naive keyword gate over the
``never/always/must`` vocabulary inflated the standing tier from a true ~50 to
112 (67 false "laws"). :func:`classify` therefore promotes to ``law`` ONLY on
:data:`LAW_TYPE` / :data:`LAW_PROVENANCE` provenance — **never** on keyword
presence. Everything the classifier is unsure about stays non-standing (a
per-file fact, still reachable via the full index).

An explicit dream-written ``tier`` (:data:`~oversteward.dream.extract.VALID_TIERS`)
on a memory's metadata OVERRIDES the derivation: ``model`` / ``cookbook`` demote a
fact out of the standing layer, and ``standing`` keeps it in (as a habit unless it
also qualifies as a law). When ``tier`` is absent — today's whole store — the
strict derivation runs, so the standing layer populates immediately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class MemoryLike(Protocol):
    """The read surface this module needs from a memory (a :class:`MemoryFile`).

    Structural typing (dependency inversion) rather than importing
    :class:`~oversteward.dream.consolidate.MemoryFile` — that import would form a
    ``consolidate -> standing -> consolidate`` cycle (:data:`DEP-001`). Any object
    exposing these members classifies; the concrete ``MemoryFile`` satisfies it.
    """

    filename: str
    description: str
    body: str
    metadata: dict[str, Any]

    def provenance(self) -> str | None: ...


# ---- kinds + the four standing groups ---------------------------------------

# The classifier's verdict for one memory. ``LAW`` / ``HABIT`` / ``GRAVEYARD`` /
# ``POINTER`` are the four standing groups; ``NON_STANDING`` stays a per-file fact.
LAW = "law"
HABIT = "habit"
GRAVEYARD = "graveyard"
POINTER = "pointer"
NON_STANDING = "non-standing"

STANDING_KINDS = (LAW, HABIT, GRAVEYARD, POINTER)

# The ONLY two law signals — provenance, never keywords (the load-bearing rule).
LAW_TYPE = "user"
LAW_PROVENANCE = "nathan-stated"

# The OS#195 reconciler's backup-variant sidecar suffix (mirrors
# ``reconcile.STEWARD_VARIANT_SUFFIX``; redefined here to keep this module free of
# a runtime import that would form a consolidate <-> standing <-> reconcile cycle).
# Such sidecars are not live facts — excluded from both enumeration and the layer.
STEWARD_VARIANT_SUFFIX = ".steward-variant.md"

# The OS#201/#203 optional two-axis frontmatter fields.
_TIER = "tier"
_SCOPE = "scope"
_DIGEST = "digest"
TIER_STANDING = "standing"

# Retirement / supersession vocabulary → the graveyard ("reach for the
# replacement, not the corpse"). Word-boundary matched over description + body.
_GRAVEYARD_RE = re.compile(
    r"\b("
    r"removed|dropped|deprecat\w*|superseded|supersedes|retired|"
    r"obsolete|no longer|use \w+ instead|replaced by|shelved"
    r")\b",
    re.IGNORECASE,
)

# Living-doc subjects → a pointer. These are the canonical docs a session should
# reach for directly, not carry as a fact. Matched over description + body.
_POINTER_RE = re.compile(
    r"(architecture\.md|oversteward\.md|inbox|data/\w+_registry\.md"
    r"|tool_registry|workflow_registry)",
    re.IGNORECASE,
)

# A tight habit signal — a genuine cross-session tool/process pattern. Kept
# deliberately narrow: a fact earns "habit" only when it names a recurring
# tool/command/workflow the operator reaches for repeatedly. When unsure, it is
# NOT standing (per the spec).
_HABIT_RE = re.compile(
    r"\b("
    r"read \S+ (?:first|instead)|"
    r"use `?\w[\w./-]*`? (?:for|instead|to)|"
    r"run \S+ (?:before|after|when)|"
    r"always run|regenerate via|"
    r"shorthand|=\s*summary|session wrap-up"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Classification:
    """One memory's standing verdict — its ``kind`` and the ``scope`` it applies to."""

    kind: str
    scope: list[str]


def _haystack(memory: MemoryLike) -> str:
    return f"{memory.description}\n{memory.body}"


def _explicit_tier(memory: MemoryLike) -> str | None:
    value = memory.metadata.get(_TIER)
    return str(value) if isinstance(value, str) and value else None


def _scope_of(memory: MemoryLike) -> list[str]:
    value = memory.metadata.get(_SCOPE)
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _is_law(memory: MemoryLike) -> bool:
    """A law ← type ``user`` OR provenance ``nathan-stated`` — NEVER by keyword."""
    return memory.metadata.get("type") == LAW_TYPE or memory.provenance() == LAW_PROVENANCE


def _derive_kind(memory: MemoryLike) -> str:
    """The strict derivation (no explicit tier): law → graveyard → pointer → habit → non-standing.

    Order matters: a law is a law even if its text mentions a retired tool; the
    provenance gate wins first. Graveyard and pointer are next (retirement and
    living-doc subjects are unambiguous). Habit is last and tightest — only a
    recurring tool/process pattern, and only when nothing above claimed it.
    """
    if _is_law(memory):
        return LAW
    text = _haystack(memory)
    if _GRAVEYARD_RE.search(text):
        return GRAVEYARD
    if _POINTER_RE.search(text):
        return POINTER
    if _HABIT_RE.search(text):
        return HABIT
    return NON_STANDING


def classify(memory: MemoryLike) -> Classification:
    """Classify one memory into a standing group or non-standing (strict).

    An explicit dream-written ``tier`` overrides the derivation: ``model`` /
    ``cookbook`` force non-standing; ``standing`` keeps the fact in the loaded
    layer (as a law when it qualifies on provenance, else a habit). With no
    explicit tier — the whole store today — the strict derivation runs.
    """
    scope = _scope_of(memory)
    tier = _explicit_tier(memory)
    if tier is not None:
        if tier == TIER_STANDING:
            return Classification(LAW if _is_law(memory) else HABIT, scope)
        return Classification(NON_STANDING, scope)
    return Classification(_derive_kind(memory), scope)


def is_steward_variant(filename: str) -> bool:
    """True for an OS#195 reconciler backup sidecar — never a live fact."""
    return filename.endswith(STEWARD_VARIANT_SUFFIX)


# ---- rendering --------------------------------------------------------------

_GROUP_HEADINGS = (
    (LAW, "## Laws"),
    (HABIT, "## Habits"),
    (GRAVEYARD, "## Graveyard"),
    (POINTER, "## Living-doc pointers"),
)


def _entry_text(memory: MemoryLike) -> str:
    """One standing-order line — the dream-written ``digest`` if set, else the description."""
    digest = memory.metadata.get(_DIGEST)
    if isinstance(digest, str) and digest.strip():
        return digest.strip()
    return memory.description


def _render_entry(memory: MemoryLike, classification: Classification) -> str:
    scope = classification.scope
    suffix = f" _(scope: {', '.join(scope)})_" if scope else ""
    return f"- [{memory.filename}]({memory.filename}) — {_entry_text(memory)}{suffix}"


_HEADER_LINES = (
    "# Standing Orders",
    "",
    "The lean always-loaded memory layer — durable laws, cross-session habits,",
    "retired approaches, and living-doc pointers. The full per-file index is in",
    "`MEMORY_FULL.md`; every fact remains reachable there.",
    "",
)


def _group_entries(memories: list[MemoryLike]) -> dict[str, list[str]]:
    """Classify each live memory once and bucket its rendered line by standing kind."""
    grouped: dict[str, list[str]] = {kind: [] for kind, _ in _GROUP_HEADINGS}
    for memory in sorted(memories, key=lambda m: m.filename):
        if is_steward_variant(memory.filename):
            continue
        classification = classify(memory)
        if classification.kind in grouped:
            grouped[classification.kind].append(_render_entry(memory, classification))
    return grouped


def render_standing_orders(memories: list[MemoryLike]) -> str:
    """Render the grouped Standing Orders layer (the always-loaded ``MEMORY.md``).

    Sidecar variants are excluded. Each memory is classified once; only the four
    standing kinds surface (non-standing facts stay in the full index only). Empty
    groups are omitted. Entries sort by filename within a group for a stable,
    diff-friendly layer.
    """
    grouped = _group_entries(memories)
    lines = list(_HEADER_LINES)
    for kind, heading in _GROUP_HEADINGS:
        entries = grouped[kind]
        if not entries:
            continue
        lines.append(heading)
        lines.append("")
        lines.extend(entries)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
