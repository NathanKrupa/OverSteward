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
type/provenance — **never** on keyword presence. And even ``nathan-stated``
provenance is not enough on its own: a durable ``project``/``reference`` *datum*
(an application limit, an endpoint topology, a comp coupon) is not
constitutional. Derivation promotes to ``law`` ONLY when the type is
:data:`LAW_TYPE` (``user``), or the type is :data:`FEEDBACK_TYPE` (``feedback``)
AND provenance is :data:`LAW_PROVENANCE` (``nathan-stated``). A ``nathan-stated``
``project``/``reference`` fact derives to ``NON_STANDING`` — it stays in
``MEMORY_FULL.md``, remains recallable, but is not always-loaded. Everything else
the classifier is unsure about likewise stays non-standing (a per-file fact,
still reachable via the full index).

An explicit dream-written ``tier`` (:data:`~oversteward.dream.extract.VALID_TIERS`)
on a memory's metadata OVERRIDES the derivation: ``model`` / ``cookbook`` demote a
fact out of the standing layer, and ``standing`` keeps it in (as a habit unless it
also qualifies as a law). When ``tier`` is absent — today's whole store — the
strict derivation runs, so the standing layer populates immediately.

THE SECOND LOAD-BEARING CONSTRAINT: the layer is always-loaded, so it is CAPPED
(:data:`STANDING_LAYER_BYTE_BUDGET`). Entries carry no file-link scaffolding — the
``[file](file)`` recall hook belongs to ``MEMORY_FULL.md``, and duplicating it here
spent half the budget on paths — and :func:`render_standing_orders` raises
:class:`StandingOrdersOverBudget` rather than hand the harness a layer to truncate.
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

# The law signals — type/provenance, never keywords (the load-bearing rule).
# A ``user`` fact is a law outright. A ``feedback`` fact is a law only when it is
# ``nathan-stated`` (Nathan-stated law vs a Claude-inferred lesson). A
# ``nathan-stated`` ``project``/``reference`` datum is durable but NOT a law.
LAW_TYPE = "user"
FEEDBACK_TYPE = "feedback"
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

# The explicit graveyard marker. A memory carrying a truthy ``superseded_by`` is
# the corpse — its subject is a retired approach and ``superseded_by`` names the
# live replacement ("reach for the replacement, not the corpse"). This is set by
# the dream supersession path or seeded by hand; it is NEVER derived from keyword
# vocabulary. Retirement words ("removed", "obsolete", "retired") appear
# incidentally in ordinary facts ("when load is removed", "the dead url_type
# column"), so a keyword scan inflated the always-loaded Graveyard the same way it
# inflated Laws — the fix is symmetric: explicit provenance, never keywords.
_SUPERSEDED_BY = "superseded_by"

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


def _superseded_target(memory: MemoryLike) -> str | None:
    """The live replacement a memory was superseded by, or None.

    A truthy value IS the explicit graveyard marker — the memory's subject is a
    retired approach and this names what to reach for instead. NEVER keyword-derived.
    """
    value = memory.metadata.get(_SUPERSEDED_BY)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _is_law(memory: MemoryLike) -> bool:
    """A law ← type ``user``, OR type ``feedback`` AND provenance ``nathan-stated``.

    NEVER by keyword. And ``nathan-stated`` alone is insufficient: a durable
    ``project``/``reference`` datum is recallable but not constitutional, so it
    does NOT derive to a law (it stays non-standing). Only ``user`` facts and
    ``nathan-stated`` ``feedback`` facts qualify.
    """
    type_ = memory.metadata.get("type")
    if type_ == LAW_TYPE:
        return True
    return type_ == FEEDBACK_TYPE and memory.provenance() == LAW_PROVENANCE


def _derive_kind(memory: MemoryLike) -> str:
    """The strict derivation (no explicit tier): law → pointer → habit → non-standing.

    Graveyard is NOT derived here — it is an explicit ``superseded_by`` marker
    handled ahead of everything in :func:`classify`. A law is a law even if its
    text mentions a retired tool; the provenance gate wins first. Pointer is next
    (living-doc subjects are unambiguous proper-noun matches). Habit is last and
    tightest — only a recurring tool/process pattern, and only when nothing above
    claimed it.
    """
    if _is_law(memory):
        return LAW
    text = _haystack(memory)
    if _POINTER_RE.search(text):
        return POINTER
    if _HABIT_RE.search(text):
        return HABIT
    return NON_STANDING


def classify(memory: MemoryLike) -> Classification:
    """Classify one memory into a standing group or non-standing (strict).

    An explicit ``superseded_by`` marker wins outright: a retirement warning is
    actively harmful to miss, so it surfaces in the always-loaded Graveyard even
    against a demoting tier. Otherwise an explicit dream-written ``tier`` overrides
    the derivation: ``model`` / ``cookbook`` force non-standing; ``standing`` keeps
    the fact in the loaded layer (as a law when it qualifies on provenance, else a
    habit). With neither marker nor tier — the whole store today — the strict
    derivation runs.
    """
    scope = _scope_of(memory)
    if _superseded_target(memory) is not None:
        return Classification(GRAVEYARD, scope)
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


def _digest_of(memory: MemoryLike) -> str | None:
    """The dream-written ``digest`` — the short imperative form of a fact — or None."""
    value = memory.metadata.get(_DIGEST)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _entry_text(memory: MemoryLike) -> str:
    """One standing-order line — the dream-written ``digest`` if set, else the description."""
    return _digest_of(memory) or memory.description


def unindexed_digest(memory: MemoryLike) -> str | None:
    """The digest text the full index would not otherwise carry, or None.

    The standing layer renders the ``digest`` while ``MEMORY_FULL.md`` renders the
    ``description``. With the file links gone from the standing layer (OS#287), a
    fact is resolved to its file by grepping its standing text in the full index —
    so a digest that does not already appear in the description would be
    unfindable, and that fact's recall hook would be broken. The full index carries
    it for exactly that reason; it is uncapped, so the bytes are free there.
    """
    digest = _digest_of(memory)
    if digest is None or digest in memory.description:
        return None
    return digest


def _render_entry(memory: MemoryLike, classification: Classification) -> str:
    """One standing-order line — the order itself, with no file-link scaffolding.

    The layer's job is to STATE the standing orders, not to be a second copy of a
    file index. ``_write_full_index`` already emits every memory to
    ``MEMORY_FULL.md`` in ``[file](file) — desc`` form, so the recall hook lives
    there; repeating each ~70-char filename twice per line here bought nothing and
    cost half the capped budget (OS#287). A fact resolves to its file by grepping
    its text in ``MEMORY_FULL.md``.
    """
    scope = classification.scope
    scope_suffix = f" _(scope: {', '.join(scope)})_" if scope else ""
    replacement = ""
    if classification.kind == GRAVEYARD:
        target = _superseded_target(memory)
        if target:
            replacement = f" → {target}"
    return f"- {_entry_text(memory)}{replacement}{scope_suffix}"


_HEADER_LINES = (
    "# Standing Orders",
    "",
    "The lean always-loaded memory layer — durable laws, cross-session habits,",
    "retired approaches, and living-doc pointers. Entries state the order itself;",
    "to reach the file behind one, grep its text in `MEMORY_FULL.md` — the full",
    "per-file index, where every fact remains reachable.",
    "",
)


# The harness that always-loads ``MEMORY.md`` caps it at 25,000 bytes and cuts
# whatever runs past the cap. That failure is silent from inside a session: a
# truncated always-loaded layer is indistinguishable from a short one, so standing
# orders simply stop arriving, with nothing but a harness warning nobody reads to
# show for it. The renderer therefore owns the cap — it refuses to emit a layer the
# harness would have to cut, rather than growing unbounded with every dream cycle
# (OS#287). The value is the harness limit itself, not a margin below it; the
# renderer's job is to notice the breach, and the operator decides what to shed.
STANDING_LAYER_BYTE_BUDGET = 25_000


class StandingOrdersOverBudget(RuntimeError):
    """The rendered standing layer would exceed :data:`STANDING_LAYER_BYTE_BUDGET`.

    Raised in place of emitting an oversized layer. Trimming to fit is deliberately
    NOT done: silently dropping the tail would reproduce the harness's own
    truncation one layer down, and a dropped standing order looks exactly like a
    fact that was never standing. The message carries the rendered size, the
    budget, and the per-group byte cost so the operator can act.
    """


def _section_bytes(entries: list[str]) -> int:
    """The rendered byte cost of one group's entries (each line plus its newline)."""
    return sum(len(entry.encode("utf-8")) + 1 for entry in entries)


def _over_budget_message(size: int, grouped: dict[str, list[str]]) -> str:
    """The loud failure — what the layer costs now, group by group, and what to do."""
    lines = [
        f"Standing Orders layer is {size} bytes against a "
        f"{STANDING_LAYER_BYTE_BUDGET}-byte budget "
        f"(over by {size - STANDING_LAYER_BYTE_BUDGET}). Refusing to emit a layer "
        "the harness would silently truncate.",
        "Section cost:",
    ]
    for kind, heading in _GROUP_HEADINGS:
        entries = grouped[kind]
        if not entries:
            continue
        noun = "entry" if len(entries) == 1 else "entries"
        lines.append(f"  {heading} — {len(entries)} {noun}, {_section_bytes(entries)} bytes")
    lines.append(
        "Shorten the `digest` on the largest entries, or demote facts out of the "
        "standing tier (`tier: model` / `tier: cookbook`) — they stay recallable "
        "via MEMORY_FULL.md."
    )
    return "\n".join(lines)


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

    Raises :class:`StandingOrdersOverBudget` when the result would exceed
    :data:`STANDING_LAYER_BYTE_BUDGET` — the layer is never emitted oversized.
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
    rendered = "\n".join(lines).rstrip("\n") + "\n"
    size = len(rendered.encode("utf-8"))
    if size > STANDING_LAYER_BYTE_BUDGET:
        raise StandingOrdersOverBudget(_over_budget_message(size, grouped))
    return rendered
