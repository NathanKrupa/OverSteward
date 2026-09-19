# ABOUTME: Guards agent cards against hand-written volatile facts and shared/.claude byte drift.
# ABOUTME: A card carries judgment and doctrine; a derivable number typed into one rots silently.

from __future__ import annotations

import re
import subprocess
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
    # Two lines of one fenced block, each an innocent command. A scanner that
    # joined fenced lines would read "4 workflows" across the newline and
    # flag a shell script as an inventory claim. The count sits at the end of
    # one line and its noun at the start of the next with no fence delimiter
    # between them — a delimiter in the middle would break the count-to-noun
    # regex on its own and the fixture would prove nothing.
    "Read the current count from the command, never from this card:\n"
    "```bash\n"
    "gh run list --limit 4\n"
    "workflows=$(gh workflow list)\n"
    "```\n"
    "Neither line above states anything about the estate.",
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
    # The reviewer runs as a separate `claude -p` process with its one
    # instruction on stdin. A dev card is launched with `tools: Bash, Read,
    # Edit, Write, Grep, Glob` and cannot launch a subagent, so a card that
    # prescribes an in-session launch prescribes a step the agent cannot take
    # (OS#493 — four pickups each rediscovered the headless form).
    "| claude -p --agent adversarial-reviewer --model opus",
    "--output-format json",
)

#: The launch shape the dev cards used to prescribe and no dispatch agent can
#: execute. Matched as prose so a comment or a parenthetical reintroducing it
#: goes red too.
REVIEWER_LAUNCH_FORBIDDEN = re.compile(r"\bTask\s+tool\b", re.IGNORECASE)

#: The loop is three rounds (`shared/references/pr-workflow.md`,
#: `shared/agents/adversarial-reviewer.md`): a `BLOCK` earns a re-review on the
#: delta, and it is the *third* `BLOCK` that hands the change to Nathan. A card
#: that stops on the second contradicts the fourth-round refusal it states two
#: lines later, and one pickup ran the three rounds and had to flag the
#: conflict (OS#493).
THIRD_BLOCK_STOPS = "a *third* `BLOCK` on the same change stops the pickup"
SECOND_BLOCK_STOPS = re.compile(r"\bsecond\b\W{0,4}BLOCK", re.IGNORECASE)


def _unwrapped(card: str) -> str:
    """Card prose with hard wraps closed, so a phrase is found wherever the wrap falls."""
    return " ".join(card.split())


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
    forbidden = REVIEWER_LAUNCH_FORBIDDEN.search(_unwrapped(text))
    assert forbidden is None, (
        f"{card.parent.name}/{card.name} launches the reviewer through a tool a "
        f"dispatch agent does not have: {forbidden.group(0)!r}"
    )


@pytest.mark.parametrize("card", _dev_cards(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_dev_card_states_that_a_block_stops_the_pickup(card: Path) -> None:
    """A verdict that cannot stop anything is a report, not a gate."""
    text = card.read_text(encoding="utf-8")
    assert "`BLOCK` means do not open the PR" in text, (
        f"{card.parent.name}/{card.name} names the reviewer but not its authority."
    )
    prose = _unwrapped(text)
    assert THIRD_BLOCK_STOPS in prose, (
        f"{card.parent.name}/{card.name} does not say which BLOCK stops the pickup; "
        f"the loop is three rounds and the third BLOCK goes to Nathan."
    )
    early_stop = SECOND_BLOCK_STOPS.search(prose)
    assert early_stop is None, (
        f"{card.parent.name}/{card.name} stops on a second BLOCK, one round short of "
        f"the cap it states beneath: {early_stop.group(0)!r}"
    )


#: A file the card writes into the worktree, named relative to it. Every such
#: file must be ignored, or the pickup leaves untracked files that a `git add .`
#: would commit and that `worktree_doctor.py teardown` (which never forces)
#: refuses over.
WORKTREE_ARTEFACT = re.compile(r"<worktree-path>/(\.review-[\w.-]+)")


def _worktree_artefacts(card: Path) -> list[str]:
    return sorted(set(WORKTREE_ARTEFACT.findall(card.read_text(encoding="utf-8"))))


def _is_ignored(path: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "--quiet", path],
            check=False,
        ).returncode
        == 0
    )


def test_the_oversteward_card_writes_review_artefacts_this_repo_ignores() -> None:
    """The card names the files; the repo's `.gitignore` has to know the same names."""
    artefacts = _worktree_artefacts(CANONICAL_DIR / "oversteward-dev.md")
    assert artefacts, "the card writes nothing into the worktree — the regex has rotted"
    tracked = [name for name in artefacts if not _is_ignored(name)]
    assert not tracked, (
        f"oversteward-dev.md writes {tracked} into the worktree and .gitignore does not "
        f"cover them: they would block teardown and could be committed."
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


# A card that names no model inherits the session's. When the session default
# moved to Opus (2026-09-16), that silently promoted every unpinned card and
# demoted nothing — no error, no diff, no way to see it from the card. The pin
# below is what makes a card's model a contract rather than a side effect
# (OS#490).

#: The aliases Claude Code documents for a card's `model:` key.
MODEL_ALIASES = frozenset({"sonnet", "opus", "haiku", "fable", "inherit"})

#: A full model id is accepted wherever an alias is — e.g. `claude-opus-5[1m]`.
MODEL_ID = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]*(?:\[[a-z0-9]+\])?$")

#: Cards whose model is part of the contract, not a preference. `architect`
#: exists only to run on a different model from the session that launches it, so
#: an unpinned `architect` is not a slower planner — it is no planner at all.
PINNED_MODELS = {"architect": "fable", "watch": "sonnet"}

#: Roles that are Opus work by the same rule that puts the dev cards there:
#: reading a repo's doctrine and out-reading the author of a diff.
OPUS_ROLES = ("adversarial-reviewer",)

#: `*-dev` cards are matched as a family rather than listed, so adding a repo
#: cannot quietly add an unpinned card.
DEV_CARD_SUFFIX = "-dev"

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_MODEL_KEY = re.compile(r"^model:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)


def _card_model(card: Path) -> str | None:
    """The card's frontmatter `model:` value, or None when it names none.

    Only the frontmatter is read: a card that *discusses* another agent's model
    in its prose has not pinned its own.
    """
    frontmatter = _FRONTMATTER.match(card.read_text(encoding="utf-8"))
    if frontmatter is None:
        return None
    found = _MODEL_KEY.search(frontmatter.group(1))
    return found.group(1) if found else None


def _expected_model(card: Path) -> str | None:
    """The model this card must pin, or None when only the vocabulary binds."""
    if card.stem.endswith(DEV_CARD_SUFFIX) or card.stem in OPUS_ROLES:
        return "opus"
    return PINNED_MODELS.get(card.stem)


def _contractual_model_cards() -> list:
    return [
        pytest.param(card, _expected_model(card), id=f"{card.parent.name}/{card.name}")
        for card in _agent_cards()
        if _expected_model(card) is not None
    ]


def test_every_card_with_a_pinned_model_is_present() -> None:
    """A pin over a card that does not exist passes vacuously — renaming one must go red."""
    present = {card.stem for card in _agent_cards()}
    missing = sorted((set(PINNED_MODELS) | set(OPUS_ROLES)) - present)
    assert not missing, f"pinned but no such card: {missing}"


def test_the_dev_card_family_is_not_empty() -> None:
    """The `*-dev` half of the pin is derived from a glob; an empty glob pins nothing."""
    assert [card for card in _agent_cards() if card.stem.endswith(DEV_CARD_SUFFIX)]


@pytest.mark.parametrize("card", _agent_cards(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_agent_card_names_a_documented_model(card: Path) -> None:
    """An absent `model:` is not a default — it is the session's model, whatever that is."""
    model = _card_model(card)
    assert model is not None, (
        f"{card.parent.name}/{card.name} names no `model:` in its frontmatter, so it "
        f"runs on whatever model the launching session happens to be using."
    )
    assert model in MODEL_ALIASES or MODEL_ID.match(model), (
        f"{card.parent.name}/{card.name} declares `model: {model}`, which is neither a "
        f"documented alias ({', '.join(sorted(MODEL_ALIASES))}) nor a full model id."
    )


@pytest.mark.parametrize(("card", "expected"), _contractual_model_cards())
def test_a_card_whose_model_is_contractual_pins_it(card: Path, expected: str) -> None:
    """Implementation and review run on opus; `architect` plans on fable; `watch` waits on sonnet."""
    assert _card_model(card) == expected, (
        f"{card.parent.name}/{card.name} must pin `model: {expected}` and declares "
        f"`model: {_card_model(card)}`."
    )
