# ABOUTME: Extraction scaffolding for the dream cycle — turns a parsed transcript into validated,
# ABOUTME: gated, secret-free candidate facts around an IN-SESSION (Max, not metered-API) extractor seam.

"""Deterministic scaffolding around the in-session extraction LLM step.

Per the design (§14-3, ``documentation/designs/sleep-time-consolidation.md``) the
extraction call itself runs **in-session on the Max subscription**, never as a
metered API call. This module therefore owns everything *around* that step and
NOTHING of the call itself:

- :class:`CandidateFact` — the §5 candidate schema, with JSON (de)serialize +
  validation that rejects malformed / unknown-enum input.
- :data:`EXTRACTION_PROMPT` / :data:`EXTRACTION_PROMPT_VERSION` — the §5 prompt
  as a versioned asset.
- :func:`signal_gate` — the §7 deterministic backstop dropping mechanically
  judgeable noise (the fuzzy judgment stays in the prompt).
- :func:`privacy_filter` — the §8 hard-block over body+description, reusing the
  estate credential-hygiene denylist; a match DROPS and logs.
- :func:`extract_candidates` — the seam: ``extractor`` is injected by the caller
  (the in-session LLM step), never hardcoded to any client.

The pipeline is: prompt + transcript → ``extractor`` → parse/validate →
signal gate → privacy filter → ``list[CandidateFact]``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

# An ``extractor`` is the in-session LLM step (§14-3): it takes the full prompt
# (extraction instructions + the parsed transcript) and returns the model's raw
# string response — expected to be a JSON list of candidate-fact objects. It is
# injected by the caller and wired to the Max-subscription session model; this
# module never constructs an API client.
Extractor = Callable[[str], str]


# ---- Schema -----------------------------------------------------------------

# Field names — named once so the schema's string keys live in one place.
_TYPE = "type"
_DESCRIPTION = "description"
_BODY = "body"
_PROVENANCE = "provenance"
_CONFIDENCE = "confidence"
_IS_PROCEDURAL = "is_procedural"

VALID_TYPES = ("user", "feedback", "project", "reference")
VALID_PROVENANCE = ("nathan-stated", "claude-inferred")
VALID_CONFIDENCE = ("high", "medium", "low")

_STRING_FIELDS = (_TYPE, _DESCRIPTION, _BODY, _PROVENANCE, _CONFIDENCE)
_FIELD_NAMES = (*_STRING_FIELDS, _IS_PROCEDURAL)
_ENUM_FIELDS = (
    (_TYPE, VALID_TYPES),
    (_PROVENANCE, VALID_PROVENANCE),
    (_CONFIDENCE, VALID_CONFIDENCE),
)


@dataclass(frozen=True)
class CandidateFact:
    """One candidate memory fact, mirroring the §5 extraction frontmatter.

    Validated at construction via :meth:`from_dict`; the dataclass itself stays a
    plain value object. ``is_procedural`` marks operational lessons (trigger +
    failure + fix) that get first-class capture per §5.
    """

    type: str
    description: str
    body: str
    provenance: str
    confidence: str
    is_procedural: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-ready)."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize this fact to a JSON object string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Any) -> CandidateFact:
        """Build + validate a fact from a decoded JSON object.

        Raises :class:`CandidateValidationError` on a non-object, a missing or
        unknown field, a wrong-typed field, or an out-of-enum value. Validation
        is strict: the in-session extractor is trusted to *produce* JSON, not to
        be correct, so malformed candidates are rejected rather than coerced.
        """
        if not isinstance(data, dict):
            raise CandidateValidationError(
                f"candidate must be a JSON object, got {type(data).__name__}"
            )
        _validate_keys(data)
        _validate_types(data)
        _validate_enums(data)
        return cls(**{name: data[name] for name in _FIELD_NAMES})


class CandidateValidationError(ValueError):
    """A decoded candidate object failed schema validation."""


def _validate_keys(data: dict[str, Any]) -> None:
    keys = set(data)
    missing = [name for name in _FIELD_NAMES if name not in keys]
    if missing:
        raise CandidateValidationError(f"missing field(s): {_join(missing)}")
    unknown = keys - set(_FIELD_NAMES)
    if unknown:
        raise CandidateValidationError(f"unknown field(s): {_join(sorted(unknown))}")


def _validate_types(data: dict[str, Any]) -> None:
    for name in _STRING_FIELDS:
        if not isinstance(data[name], str):
            raise CandidateValidationError(_field_error(name, "must be a string"))
    if not isinstance(data[_IS_PROCEDURAL], bool):
        raise CandidateValidationError(_field_error(_IS_PROCEDURAL, "must be a bool"))


def _validate_enums(data: dict[str, Any]) -> None:
    for name, allowed in _ENUM_FIELDS:
        if data[name] not in allowed:
            detail = f"has unknown value {data[name]!r}; allowed: {_join(allowed)}"
            raise CandidateValidationError(_field_error(name, detail))


def _field_error(name: str, detail: str) -> str:
    return f"field '{name}' {detail}"


def _join(values: Any) -> str:
    return ", ".join(values)


def parse_candidates(raw: str) -> list[CandidateFact]:
    """Parse the extractor's raw JSON response into validated candidates.

    The response must be a JSON list of objects. A non-list top level, invalid
    JSON, or any object failing :meth:`CandidateFact.from_dict` raises
    :class:`CandidateValidationError` — the caller decides whether to retry the
    in-session extraction or surface the failure.
    """
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateValidationError(f"extractor output is not valid JSON: {exc}") from exc
    if not isinstance(decoded, list):
        raise CandidateValidationError(
            f"extractor output must be a JSON list, got {type(decoded).__name__}"
        )
    return [CandidateFact.from_dict(item) for item in decoded]


# ---- Extraction prompt asset (§5) -------------------------------------------

EXTRACTION_PROMPT_VERSION = "1"

EXTRACTION_PROMPT = """\
You are reading a development-session transcript to extract DURABLE memory for a
future session. Output ONLY a JSON list of candidate facts — no prose, no
markdown fence. Each item must be an object with exactly these fields:

  {
    "type": "user" | "feedback" | "project" | "reference",
    "description": "<one line — the recall-relevance hook>",
    "body": "<the fact in full>",
    "provenance": "nathan-stated" | "claude-inferred",
    "confidence": "high" | "medium" | "low",
    "is_procedural": true | false
  }

Extract ONLY facts that will matter in a FUTURE session:
  - user preferences and rulings (type "user"),
  - operational lessons — what failed and the fix (type "feedback",
    is_procedural true),
  - durable project state NOT derivable from code or git (type "project"),
  - external references worth re-finding (type "reference").

A procedural lesson MUST state the trigger, the failure, and the corrective
action: "X failed because Y; do Z next time."

Do NOT extract:
  - anything recoverable from the repo, code, or git history,
  - transient task chatter or task-local state,
  - one-off values (a specific run id, a today-only path),
  - restatements of CLAUDE.md or other standing instructions.

When in doubt, OMIT — a strict deterministic signal gate runs after you, and a
privacy filter hard-blocks any secret, so do not emit credentials or tokens.

Set "provenance" to "nathan-stated" only for facts Nathan asserted directly;
everything you concluded yourself is "claude-inferred". Set "confidence" to
"low" for single-mention claims you could not corroborate in the transcript.

Transcript follows:
---
%TRANSCRIPT%
---
"""


def build_extraction_prompt(parsed_transcript: str) -> str:
    """Render the versioned §5 extraction prompt over a parsed transcript.

    Uses a token replacement rather than ``str.format`` because the prompt body
    contains literal ``{`` / ``}`` from the JSON schema example.
    """
    return EXTRACTION_PROMPT.replace("%TRANSCRIPT%", parsed_transcript)


# ---- Signal gate (§7) -------------------------------------------------------


def signal_gate(candidates: list[CandidateFact]) -> list[CandidateFact]:
    """Drop the mechanically-judgeable §7 noise; keep the rest.

    Deterministic backstop only — the fuzzy "is this durable?" judgment stays in
    the extraction prompt. This drops:

    - empty or whitespace-only ``description`` (no recall hook),
    - duplicate descriptions (case-insensitive, whitespace-collapsed) — only the
      first occurrence survives,
    - low-confidence single-mention claims with no corroboration: a ``low``
      confidence, ``claude-inferred`` candidate that appears once.

    The single-mention rule is conservative: a ``low``/``claude-inferred`` fact
    whose description recurs (duplicate-collapsed above) IS corroboration, so a
    fact is only dropped on this rule when it stands alone.
    """
    counts = _description_counts(candidates)
    kept: list[CandidateFact] = []
    seen: set[str] = set()
    for cand in candidates:
        key = _normalize(cand.description)
        if _is_noise(cand, key, seen, counts):
            continue
        seen.add(key)
        kept.append(cand)
    return kept


def _description_counts(candidates: list[CandidateFact]) -> dict[str, int]:
    """Count non-empty normalized descriptions for the corroboration check."""
    counts: dict[str, int] = {}
    for cand in candidates:
        key = _normalize(cand.description)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _is_noise(cand: CandidateFact, key: str, seen: set[str], counts: dict[str, int]) -> bool:
    """True if this candidate is mechanically-judgeable §7 noise (and log why)."""
    if not key:
        log.info("signal_gate dropped candidate with empty description")
        return True
    if key in seen:
        log.info("signal_gate dropped duplicate description: %s", cand.description)
        return True
    if _is_uncorroborated_low(cand) and counts.get(key, 0) <= 1:
        log.info("signal_gate dropped low-confidence single-mention claim: %s", cand.description)
        return True
    return False


def _normalize(text: str) -> str:
    """Whitespace-collapsed, lowercased key for duplicate detection."""
    return " ".join(text.split()).lower()


def _is_uncorroborated_low(cand: CandidateFact) -> bool:
    """A low-confidence, claude-inferred candidate — the §7 hold-don't-write case."""
    return cand.confidence == "low" and cand.provenance == "claude-inferred"


# ---- Privacy filter (§8) ----------------------------------------------------

# Hard-block denylist, reusing the estate credential-hygiene patterns
# (``~/.claude/hooks/check_db_access.py`` + ``shared/references/credential-hygiene.md``).
# A match DROPS the candidate and logs — this is a gate, NOT a scrubber: we never
# write a redacted-but-still-suspicious fact (§8).
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # postgresql://user:pass@host — a credentialed connection URL
    re.compile(r"postgres(?:ql)?://[^\s/@]+:[^\s/@]+@", re.IGNORECASE),
    # *_DATABASE_URL references (NEON_DATABASE_URL, AG_TENANT_DATABASE_URL, ...)
    re.compile(r"\b(?:[A-Z_]*_)?DATABASE_URL\b"),
    # Anthropic / OpenAI style API keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),
    # GitHub tokens (classic + fine-grained + app)
    re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Generic bearer/secret token assignments: TOKEN=..., API_KEY: ...,
    # SECRET="...", with a non-trivial value
    re.compile(
        r"\b[A-Z0-9_]*(?:TOKEN|API[_-]?KEY|SECRET|PASSWORD|PASSWD)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}",
        re.IGNORECASE,
    ),
    # AWS access key id
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _matched_secret(text: str) -> str | None:
    """Return the name of the first matching denylist pattern, or None."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def privacy_filter(candidates: list[CandidateFact]) -> list[CandidateFact]:
    """Hard-block any candidate whose body+description matches a secret pattern (§8).

    A match DROPS the candidate and logs a warning — the fact is never written,
    not even redacted. This protects against ever persisting a leaked credential
    into the memory store.
    """
    kept: list[CandidateFact] = []
    for cand in candidates:
        haystack = f"{cand.description}\n{cand.body}"
        matched = _matched_secret(haystack)
        if matched is not None:
            log.warning(
                "privacy_filter DROPPED candidate (matched credential pattern %s): %r",
                matched,
                cand.description,
            )
            continue
        kept.append(cand)
    return kept


# ---- Seam (§5 / §14-3) ------------------------------------------------------


def extract_candidates(
    parsed_transcript: str,
    *,
    extractor: Extractor,
) -> list[CandidateFact]:
    """Run the full extraction pipeline against an INJECTED extractor.

    ``extractor`` is the in-session LLM step (§14-3) — wired by the caller to the
    Max-subscription session model, NEVER a metered API client constructed here.
    It receives the rendered prompt (instructions + transcript) and returns the
    model's raw JSON-list response.

    Pipeline: build prompt → ``extractor`` → :func:`parse_candidates` (validate)
    → :func:`signal_gate` → :func:`privacy_filter` → ``list[CandidateFact]``.

    Raises :class:`CandidateValidationError` if the extractor output is not a
    valid JSON list of well-formed candidates.
    """
    prompt = build_extraction_prompt(parsed_transcript)
    raw = extractor(prompt)
    candidates = parse_candidates(raw)
    candidates = signal_gate(candidates)
    candidates = privacy_filter(candidates)
    return candidates
