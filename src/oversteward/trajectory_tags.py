# ABOUTME: Validates the `[category]` and `→ promote:` tags every trajectory lesson bullet owes (OS#329).
# ABOUTME: Parses capture sections and the `pr:` line; reports untagged bullets and pr placeholders.

"""Tag validation for trajectory notes.

The trajectory TEMPLATE asks every lesson bullet for a leading ``[category]``
and — in *What was learned* — a trailing ``→ promote: <target>``. Both drive
downstream routing: the analyzer files a cluster by its dominant category, and
:mod:`oversteward.dream.promotion` builds the promotion worklist from the
``promote:`` targets. As of 2026-08-08, 52% of "What was learned" bullets across
OverSteward's corpus carried no ``promote:`` tag and 38% of "What didn't"
bullets no ``[category]`` — so the two sections a reader actually looks at
rendered empty while every real pattern sat in the "Other" bucket, and half the
corpus could never reach the promotion worklist at all (OS#329, Fiscus#101).

Encouragement did not close that gap, so this module is the enforcement side.
It is deliberately **forward-looking**: it validates the note it is handed, and
the gate that calls it (``scripts/lint/trajectory_tags.py``, wired into
pre-commit) only ever hands it notes a commit adds or modifies. The 123 legacy
notes are exempt by construction — nothing retro-tags them, and the analyzer
already tolerates untagged legacy bullets by design.

**A note whose capture sections cannot be found is reported unreadable, not
clean.** Returning "0 violations" for a file the parser could not understand is
the false green this whole surface exists to remove: "found nothing" and "could
not look" must never render the same (pr-workflow.md § Inert controls).

The ``promote:`` check reuses :func:`oversteward.dream.promotion.parse_promote_target`
rather than re-implementing it. That is the point — the gate must accept exactly
what the consumer can read. A bullet that trails prose *after* its ``promote:``
tag is invisible to the analyzer's end-anchored regex, so a gate with its own
looser pattern would pass bullets that still route nowhere.

The same pass reads one front-matter line, ``pr:``. A note is written before
its PR exists, so it is named by its branch and carries no ``pr:`` line until
the PR does (OS#696). A ``pr:`` value that is not ``<repo>#<number>`` is a
placeholder for a number nobody knows yet, and is reported. Whether a
well-formed number names the PR the branch actually opened needs GitHub, and
is OS#458's question, not this offline gate's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from oversteward.dream.promotion import KNOWN_TARGETS, parse_promote_target

#: The fixed category vocabulary, as the TEMPLATE prescribes it.
CATEGORIES: tuple[str, ...] = ("design", "functional", "tooling", "process", "outcome")

#: The three sections that carry lesson bullets. Matched as heading *prefixes*
#: because "What didn't" legitimately trails its cost legend.
SECTION_WORKED = "What worked"
SECTION_DIDNT = "What didn't"
SECTION_LEARNED = "What was learned"
CAPTURE_SECTIONS: tuple[str, ...] = (SECTION_WORKED, SECTION_DIDNT, SECTION_LEARNED)

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_LEADING_TAG_RE = re.compile(r"^\[([^\]]*)\]")
_PROMOTE_MENTION_RE = re.compile(r"promote\s*:", re.IGNORECASE)

#: The section name a front-matter finding is reported under.
SECTION_FRONT_MATTER = "front matter"

#: What a `pr:` line may hold: the number of a PR that exists, optionally with
#: the owner. Anything else (``TBD``, ``<N>``, ``pending``, prose) is a
#: placeholder for a number nobody knows yet, and a placeholder is what invites
#: the fix-up commit after review that no verdict covers (OS#696).
PR_VALUE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?#[0-9]+$")
PR_ALLOWED: tuple[str, ...] = ("<repo>#<number> of a PR that already exists", "no `pr:` line")
_PR_LINE_RE = re.compile(r"^pr:(.*)$")
_YAML_COMMENT_RE = re.compile(r"\s+#.*$")

#: Cheap keyword hints for the "did you mean" suggestion. Deliberately not an
#: LLM and deliberately advisory — a wrong suggestion costs the author a moment,
#: a wrong *auto-tag* would poison the corpus the analyzer reads.
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "tooling": (
        "venv", "script", "command", "cli", "pytest", "gaudi", "hook", "ruff",
        "lint", "gate", "uv ", "pre-commit", "worktree", "makefile", "binary",
    ),
    "process": (
        "dispatch", "playbook", "pr ", "review", "issue", "scope", "branch",
        "merge", "handoff", "session", "workflow", "comment", "re-scope",
    ),
    "design": (
        "architecture", "layer", "seam", "interface", "module", "abstraction",
        "refactor", "structure", "coupling", "service", "boundary", "dataclass",
    ),
    "functional": (
        "bug", "behaviour", "behavior", "correctness", "edge case", "regression",
        "feature", "parse", "validation", "off-by-one", "crash",
    ),
    "outcome": (
        "shipped", "merged", "measured", "reduced", "improved", "coverage",
        "impact", "latency", "throughput", "resulted",
    ),
}


class UnreadableNoteError(RuntimeError):
    """The file could not be read, or carries none of the three capture sections.

    Raised rather than returning an empty violation list, so a note the parser
    does not understand can never be reported as a clean one.
    """


@dataclass(frozen=True)
class Bullet:
    """One top-level lesson bullet, with its wrapped continuation lines joined."""

    line: int
    section: str
    text: str


@dataclass(frozen=True)
class Violation:
    """One untagged or mis-tagged bullet, with everything a fix needs."""

    path: Path
    line: int
    section: str
    bullet: str
    reason: str
    allowed: tuple[str, ...]
    suggestion: str | None = None


@dataclass(frozen=True)
class NoteReport:
    """The verdict for a single note."""

    path: Path
    sections_found: tuple[str, ...]
    bullets_checked: int
    violations: tuple[Violation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def _heading_section(line: str) -> str | None:
    """The capture section a heading opens, or ``None`` for any other heading.

    Returning ``None`` for a non-capture heading is what closes the previous
    section — bullets under *Tools* or *Open threads* carry no tags and must not
    be judged as though they did.
    """
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    heading = match.group(1).strip().replace("’", "'").casefold()
    for section in CAPTURE_SECTIONS:
        if heading.startswith(section.casefold()):
            return section
    return None


def iter_bullets(text: str) -> Iterator[Bullet]:
    """Yield every top-level bullet inside the three capture sections.

    Fenced code and the TEMPLATE's guidance blockquotes are skipped; wrapped
    continuation lines and nested sub-bullets are folded into their parent, so a
    ``promote:`` tag that wrapped onto the next line is still found where the
    analyzer's end-anchored regex will find it.
    """
    state = _ScanState()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        finished, state = _scan_line(state, lineno, raw)
        if finished is not None:
            yield finished
    if state.current is not None:
        yield state.current


@dataclass(frozen=True)
class _ScanState:
    """Line-scanner state: the open section, fence flag, and in-progress bullet."""

    section: str | None = None
    in_fence: bool = False
    current: Bullet | None = None


def _scan_line(state: _ScanState, lineno: int, raw: str) -> tuple[Bullet | None, _ScanState]:
    """Fold one line into the scan, returning any bullet it completed."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        return state.current, replace(state, in_fence=not state.in_fence, current=None)
    if state.in_fence:
        return None, state
    if raw.lstrip().startswith("#"):
        return state.current, _ScanState(section=_heading_section(raw))
    if state.section is None or stripped.startswith(">"):
        return None, state
    if raw.startswith("- "):
        opened = Bullet(line=lineno, section=state.section, text=stripped[2:].strip())
        return state.current, replace(state, current=opened)
    if state.current is None:
        return None, state
    if not stripped:
        return state.current, replace(state, current=None)
    joined = replace(state.current, text=f"{state.current.text} {stripped}")
    return None, replace(state, current=joined)


def suggest_category(text: str) -> str | None:
    """A cheap keyword-scored category guess, or ``None`` when nothing matches.

    Advisory only. The author tags the bullet; this just shortens the walk back.
    """
    lowered = text.casefold()
    scores = {
        category: sum(hint in lowered for hint in hints)
        for category, hints in _CATEGORY_HINTS.items()
    }
    best = max(scores, key=lambda category: (scores[category], -CATEGORIES.index(category)))
    return best if scores[best] else None


@dataclass(frozen=True)
class _Judgement:
    """What is wrong with one bullet, before it knows which file it lives in.

    The checkers judge a bullet; only the note-level pass knows the path. Keeping
    them apart is what stops ``path`` being threaded through every checker for no
    use of its own.
    """

    reason: str
    allowed: tuple[str, ...]
    suggestion: str | None = None


def _judge_category(bullet: Bullet) -> _Judgement | None:
    """The `[category]` verdict for one bullet."""
    match = _LEADING_TAG_RE.match(bullet.text)
    if match is None:
        reason = "missing leading `[category]` tag"
    elif match.group(1).strip().casefold() in CATEGORIES:
        return None
    else:
        reason = f"unknown category `[{match.group(1)}]`"
    return _Judgement(reason, CATEGORIES, suggest_category(bullet.text))


def _judge_promote(bullet: Bullet) -> _Judgement | None:
    """The `→ promote:` verdict for one *What was learned* bullet."""
    if parse_promote_target(bullet.text):
        return None
    if _PROMOTE_MENTION_RE.search(bullet.text):
        reason = (
            "`promote:` tag is present but the analyzer cannot read it — the "
            "target must be the last thing on the bullet, and one of the "
            "listed values"
        )
    else:
        reason = "missing trailing `→ promote:` tag"
    return _Judgement(reason, KNOWN_TARGETS)


def _judge_bullet(bullet: Bullet) -> Iterator[_Judgement]:
    """Every verdict one bullet earns, in reading order."""
    category = _judge_category(bullet)
    if category is not None:
        yield category
    if bullet.section == SECTION_LEARNED:
        promote = _judge_promote(bullet)
        if promote is not None:
            yield promote


def _front_matter(text: str) -> Iterator[tuple[int, str]]:
    """Each numbered line of the leading ``---`` block; nothing when there is none.

    A leading byte-order mark is not allowed to hide the block.
    """
    lines = text.removeprefix("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return
    for lineno, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return
        yield lineno, line


def _pr_value(raw: str) -> str:
    """A `pr:` line's value, without a trailing YAML comment or quotes."""
    return _YAML_COMMENT_RE.sub("", raw).strip().strip("'\"")


def _names_a_pr(raw: str, following: list[tuple[int, str]]) -> bool:
    """Whether a `pr:` line's raw value is a real PR number or truly empty."""
    value = _pr_value(raw)
    if value:
        return PR_VALUE_RE.match(value) is not None
    continued = bool(following) and following[0][1][:1] in (" ", "\t", "-")
    return not raw.strip() and not continued


def _judge_pr_lines(path: Path, text: str) -> Iterator[Violation]:
    """A finding for each front-matter `pr:` line naming no real PR.

    A truly empty `pr:` line passes, and so does none at all: a note is written
    before its PR exists, so it is named by its branch and its PR is the one
    whose diff adds it. A value that pretends to a number nobody knows yet is a
    finding, and so is a line holding nothing but a comment (``pr: #TBD``, which
    YAML reads as empty) or an empty line carrying an indented list beneath it.
    """
    lines = list(_front_matter(text))
    for index, (lineno, line) in enumerate(lines):
        match = _PR_LINE_RE.match(line)
        if match is None:
            continue
        if _names_a_pr(match.group(1), lines[index + 1 : index + 2]):
            continue
        yield Violation(
            path=path,
            line=lineno,
            section=SECTION_FRONT_MATTER,
            bullet=line.strip(),
            reason=(
                "`pr:` names no PR that exists — leave the line out until the PR "
                "exists; never predict the number or write a placeholder (OS#696)"
            ),
            allowed=PR_ALLOWED,
        )


def _require_capture_sections(path: Path, text: str) -> tuple[str, ...]:
    """The capture sections the note carries; raises when it carries none."""
    sections = tuple(s for s in CAPTURE_SECTIONS if _has_section(text, s))
    if sections:
        return sections
    raise UnreadableNoteError(
        f"{path}: none of the capture sections "
        f"({', '.join(CAPTURE_SECTIONS)}) were found — the note does not "
        "follow documentation/trajectories/TEMPLATE.md, so its lesson "
        "bullets cannot be validated or routed."
    )


def validate_text(path: Path, text: str) -> NoteReport:
    """Validate one note's already-read body.

    Raises :class:`UnreadableNoteError` when none of the three capture sections
    is present — an unparseable note is a finding, not a pass.
    """
    sections = _require_capture_sections(path, text)
    bullets = list(iter_bullets(text))
    violations = tuple(_judge_pr_lines(path, text)) + tuple(
        Violation(
            path=path,
            line=bullet.line,
            section=bullet.section,
            bullet=bullet.text,
            reason=judgement.reason,
            allowed=judgement.allowed,
            suggestion=judgement.suggestion,
        )
        for bullet in bullets
        for judgement in _judge_bullet(bullet)
    )
    return NoteReport(
        path=path,
        sections_found=sections,
        bullets_checked=len(bullets),
        violations=violations,
    )


def _has_section(text: str, section: str) -> bool:
    return any(_heading_section(line) == section for line in text.splitlines())


def validate_note(path: Path) -> NoteReport:
    """Validate one note on disk. An unreadable file raises, never passes."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnreadableNoteError(f"{path}: cannot be read — {exc}") from exc
    return validate_text(path, text)


def format_violation(violation: Violation) -> str:
    """One violation as the multi-line block a committing author reads."""
    bullet = violation.bullet
    if len(bullet) > 160:
        bullet = f"{bullet[:157]}..."
    label = "line:    " if violation.section == SECTION_FRONT_MATTER else "bullet:  - "
    lines = [
        f"{violation.path}:{violation.line}: [{violation.section}] {violation.reason}",
        f"    {label}{bullet}",
        f"    allowed: {' | '.join(violation.allowed)}",
    ]
    if violation.suggestion:
        lines.append(f"    suggest: [{violation.suggestion}]")
    return "\n".join(lines)
