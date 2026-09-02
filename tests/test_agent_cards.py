# ABOUTME: Guards agent cards against hand-written volatile facts and shared/.claude byte drift.
# ABOUTME: A card carries judgment and doctrine; a derivable number typed into one rots silently.

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = REPO_ROOT / "shared" / "agents"
DEPLOYED_DIR = REPO_ROOT / ".claude" / "agents"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# A count is volatile whether it is typed as a digit or spelled out: "the two
# sanctioned gate shells" rots exactly as fast as "the 2 sanctioned gate
# shells", and it is the spelled form that prose reaches for. "One" is left out
# deliberately — "one PR = one logical change" is doctrine, not an inventory.
_SPELLED_COUNT = "two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
_COUNT = rf"(?:\d[\d,]*\+?|{_SPELLED_COUNT})"

# Things the estate accumulates. Any of them counted in prose is a number that
# was true on the day it was typed.
_COUNTABLE = (
    r"tools?|tests?|categories|articles|lines|files|shells?|scripts?|hooks?|"
    r"agents?|cards?|skills?|repos?|repositories|gates?|checks?|workflows?|"
    r"cases?|probes?|sections?|commands?|fixtures?|mutations?"
)

# Shapes that were true once and are wrong now. Each is a *derivable* fact — the
# card must state the command that answers it, never the answer itself.
VOLATILE_SHAPES = {
    "asserted-inventory-count": re.compile(
        # Up to three words may sit between the count and the noun — the
        # wording that shipped the false positive was "the two sanctioned
        # commit-time gate shells".
        rf"\b{_COUNT}\s+(?:[\w-]+\s+){{0,3}}(?:{_COUNTABLE})\b",
        re.IGNORECASE,
    ),
    "asserted-approximate-timing": re.compile(
        r"~\s*\d+(?:\.\d+)?\s*(?:s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b"
    ),
    "restated-playbook-cap": re.compile(r"\b\d+\s*/\s*\d+\s+cap\b"),
}

#: A template slot the author fills in. `<one or two lines>` instructs the
#: author how long to write; it asserts nothing about the estate and cannot rot.
_PLACEHOLDER = re.compile(r"<[^<>]{0,120}>")

#: The fixture that makes each shape fire. A pattern nobody has watched catch
#: anything is a pattern that may catch nothing (`pr-workflow.md` § False
#: greens: a new check ships with the fixture that makes it fail).
VOLATILE_EXEMPLARS = {
    "asserted-inventory-count": [
        # Verbatim from PR#432's brief. It taught every reviewer to flag three
        # of this repo's own sanctioned shells, because the count was written
        # down instead of derived (OS#440, verdict finding 2).
        "**`sys.path` manipulation** outside the two sanctioned commit-time gate",
        "the repo ships 47 tools",
        "all three dispatch agents read this first",
        # The same claim as it is actually written in a card: hard-wrapped, so
        # the count sits on one physical line and its noun on the next. A
        # line-by-line scan finds nothing here, which is what made an innocent
        # reflow enough to disarm the guard (OS#442, finding 1).
        "**`sys.path` manipulation** outside the two sanctioned commit-time\n"
        "gate shells is refused by the hook.",
        # `shells?` had no exemplar of its own: every fixture that appeared to
        # exercise it also matched via `gates?`, so deleting the alternation
        # left the suite green. Here "shells" is the only countable within
        # reach of the count, so the alternation is load-bearing.
        "the two commit-time shells run on every commit",
    ],
    "asserted-approximate-timing": ["the sweep takes ~30s end to end"],
    "restated-playbook-cap": ["keep the diff under the 12/400 cap"],
}

#: Prose that must stay legal, or the guard cries wolf and gets ignored.
CLEAN_PROSE = [
    "One PR = one logical change.",
    "Read `git grep -n \"sys.path\" -- '*.py'` rather than trusting a count.",
    "The verdict is three-valued, and a skip is not a pass.",
    "<one or two lines>",
    "- `<file>` — <what>",
    # Wrapped prose that claims nothing: joining must widen what the guard can
    # see without widening what it fires on.
    "Every card is hard-wrapped prose, and a claim can straddle the wrap; a\n"
    "scan that reads one physical line at a time never sees it.",
    # Two paragraphs, each innocent. Joining across the blank line would
    # manufacture "2026 Cards" out of a year and a following sentence.
    "The estate has run this gate since 2026\n"
    "\n"
    "Cards that state a count instead of a command rot.",
    # Two list items, each innocent. A bullet opens a new logical unit even
    # with no blank line above it.
    "- The hook has refused this shape since 2026\n"
    "- Cards that restate a count rot within weeks.",
    # A fenced command and the prose after it are different units: joining
    # them turns an argument into an inventory claim.
    "Run the sweep yourself rather than trusting a number here:\n"
    "```bash\n"
    "gh run list --limit 4\n"
    "```\n"
    "workflows exist today; the command above is the answer, never this card.",
]

#: Delimits a fenced block. Its lines are commands, not prose, so they are
#: scanned on their own and never joined to the paragraphs around them.
_FENCE = re.compile(r"^\s*(?:```|~~~)")

#: A heading or a list marker opens a new logical unit even with no blank line
#: above it. Joining across one would invent a sentence neither line wrote.
_UNIT_BREAK = re.compile(r"^\s*(?:#{1,6}\s|(?:[-*+]|\d+[.)])\s)")


@dataclass(frozen=True)
class Paragraph:
    """One logical unit of card prose, and the physical line it opens at."""

    start_line: int
    text: str


def _assertions_only(line: str) -> str:
    """The line with template placeholders removed, since a slot claims nothing."""
    return _PLACEHOLDER.sub(" ", line)


def _numbered_lines(card: str) -> Iterator[tuple[int, str, bool]]:
    """Each line, its number, and whether it is fenced code — which is never joined.

    A fence delimiter yields as a blank line, so it ends the unit above it
    without becoming prose of its own.
    """
    in_fence = False
    for number, line in enumerate(card.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            yield number, "", False
            continue
        yield number, line.strip(), in_fence


def _paragraphs(card: str) -> list[Paragraph]:
    """Card prose as logical units — wrapped lines joined, everything else apart.

    Every card is hard-wrapped, so a count and its noun routinely straddle a
    line break and a per-line scan sees neither half (OS#442). A blank line, a
    fence delimiter, a heading and a list marker each end a unit, because
    joining across one would fabricate a claim the card never made.
    """
    units: list[Paragraph] = []
    current: list[str] = []
    start = 0
    for number, line, fenced in _numbered_lines(card):
        if current and (fenced or not line or _UNIT_BREAK.match(line)):
            units.append(Paragraph(start_line=start, text=" ".join(current)))
            current = []
        if not line:
            continue
        if fenced:
            units.append(Paragraph(start_line=number, text=line))
            continue
        if not current:
            start = number
        current.append(line)
    if current:
        units.append(Paragraph(start_line=start, text=" ".join(current)))
    return units


def _volatile_findings(paragraph: str) -> list[str]:
    """Every shape that fires on one logical unit of card prose."""
    cleaned = _assertions_only(paragraph)
    return [shape for shape, pattern in VOLATILE_SHAPES.items() if pattern.search(cleaned)]


def _volatile_findings_in(card: str) -> list[str]:
    """Each rotting claim in a card, named with the line its paragraph opens at."""
    return [
        f"line {unit.start_line}: [{shape}] {unit.text[:160]}"
        for unit in _paragraphs(card)
        for shape in _volatile_findings(unit.text)
    ]


def test_every_volatile_shape_has_an_exemplar_that_makes_it_fire() -> None:
    """A shape with no negative fixture is a guard nobody has proven can bite."""
    assert set(VOLATILE_EXEMPLARS) == set(VOLATILE_SHAPES)


@pytest.mark.parametrize(
    ("shape", "text"),
    [(shape, text) for shape, texts in VOLATILE_EXEMPLARS.items() for text in texts],
)
def test_a_volatile_shape_catches_the_wording_that_shipped(shape: str, text: str) -> None:
    findings = _volatile_findings_in(text)
    assert any(f"[{shape}]" in finding for finding in findings), (
        f"[{shape}] no longer catches: {text}"
    )


@pytest.mark.parametrize("text", CLEAN_PROSE)
def test_ordinary_card_prose_is_not_flagged(text: str) -> None:
    """A guard that cries wolf gets overridden reflexively."""
    assert not _volatile_findings_in(text)


# "OverSteward has no CI" misled at least two pickups (issue #328). The claim is
# checkable against this repo, so the guard is derived rather than hand-listed.
NO_CI_CLAIM = re.compile(r"\bno\s+CI\b", re.IGNORECASE)


MARKDOWN_GLOB = "*.md"


def _cards_in(directory: Path) -> list[Path]:
    return sorted(directory.glob(MARKDOWN_GLOB))


def _agent_cards() -> list[Path]:
    return _cards_in(CANONICAL_DIR) + _cards_in(DEPLOYED_DIR)


def _card_pair(name: str) -> tuple[Path, Path]:
    """The canonical source and its deployed byte-copy, in that order."""
    return CANONICAL_DIR / name, DEPLOYED_DIR / name


def _paired_card_names() -> list[str]:
    canonical = {p.name for p in _cards_in(CANONICAL_DIR)}
    deployed = {p.name for p in _cards_in(DEPLOYED_DIR)}
    return sorted(canonical & deployed)


def test_agent_card_directories_are_populated() -> None:
    """A guard over an empty glob passes vacuously — assert there is something to guard."""
    assert _paired_card_names(), "no shared/.claude agent-card pairs found"


@pytest.mark.parametrize("name", _paired_card_names())
def test_canonical_and_deployed_cards_are_byte_identical(name: str) -> None:
    """`shared/agents/` is canonical; `.claude/agents/` is its byte-copy. Edit one, copy."""
    canonical_card, deployed_card = _card_pair(name)
    canonical = canonical_card.read_bytes()
    deployed = deployed_card.read_bytes()
    assert canonical == deployed, (
        f"{name} has drifted: shared/agents/{name} != .claude/agents/{name}. "
        f"Edit the canonical copy and byte-copy it across; never dual-edit."
    )


@pytest.mark.parametrize("card", _agent_cards(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_agent_cards_carry_no_hand_written_volatile_facts(card: Path) -> None:
    """State the command that answers a derivable fact, never the answer."""
    findings = _volatile_findings_in(card.read_text(encoding="utf-8"))
    assert not findings, (
        f"{card.parent.name}/{card.name} states a derivable fact that will rot "
        f"(line numbers name where the paragraph opens):\n  "
        + "\n  ".join(findings)
        + "\nReplace it with the command that answers it."
    )


DEV_CARD_GLOB = "*-dev.md"

#: The reviewer only exists if every card that opens a PR runs it. A card that
#: skips the step is not a card with a gap — it is a repo with no reviewer
#: (OS#428: "added to every *-dev card in the same PR, or the reviewer is
#: decoration").
REVIEWER_STEP_MARKERS = (
    "## Adversarial review",
    "assemble_review_input.py",
    "require_review_verdict.py",
)


def _dev_cards() -> list[Path]:
    return sorted(CANONICAL_DIR.glob(DEV_CARD_GLOB)) + sorted(DEPLOYED_DIR.glob(DEV_CARD_GLOB))


def test_there_are_dev_cards_to_check() -> None:
    """A parametrized guard over an empty glob passes vacuously."""
    assert _dev_cards()


@pytest.mark.parametrize("card", _dev_cards(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_dev_card_runs_the_adversarial_reviewer_before_opening_a_pr(card: Path) -> None:
    text = card.read_text(encoding="utf-8")
    missing = [marker for marker in REVIEWER_STEP_MARKERS if marker not in text]
    assert not missing, (
        f"{card.parent.name}/{card.name} does not run the adversarial reviewer "
        f"(missing: {', '.join(missing)}). A dev card that opens a PR without a "
        f"verdict makes the reviewer decoration — see shared/agents/adversarial-reviewer.md."
    )


@pytest.mark.parametrize("card", _dev_cards(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_dev_card_states_that_a_block_stops_the_pickup(card: Path) -> None:
    """A verdict that cannot stop anything is a report, not a gate."""
    text = card.read_text(encoding="utf-8")
    assert "`BLOCK` means do not open the PR" in text, (
        f"{card.parent.name}/{card.name} names the reviewer but not its authority."
    )


def test_the_reviewer_card_itself_is_deployed_alongside_the_dev_cards() -> None:
    """The cards reference an agent; the agent has to exist where they run."""
    canonical = CANONICAL_DIR / "adversarial-reviewer.md"
    deployed = DEPLOYED_DIR / "adversarial-reviewer.md"
    assert canonical.is_file() and deployed.is_file()
    assert canonical.read_bytes() == deployed.read_bytes()


def test_oversteward_card_does_not_deny_the_ci_this_repo_has() -> None:
    """The card's CI-presence claim is checked against this repo, not against a memory."""
    workflows = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not workflows:
        pytest.skip("this repo currently defines no workflows; the claim would be true")
    for card in _card_pair("oversteward-dev.md"):
        offenders = [
            line.strip()
            for line in card.read_text(encoding="utf-8").splitlines()
            if NO_CI_CLAIM.search(line)
        ]
        assert not offenders, (
            f"{card.parent.name}/{card.name} claims OverSteward has no CI, but "
            f"{[w.name for w in workflows]} exist:\n  " + "\n  ".join(offenders)
        )
