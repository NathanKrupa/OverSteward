# ABOUTME: Guards agent cards against hand-written volatile facts and shared/.claude byte drift.
# ABOUTME: A card carries judgment and doctrine; a derivable number typed into one rots silently.

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = REPO_ROOT / "shared" / "agents"
DEPLOYED_DIR = REPO_ROOT / ".claude" / "agents"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Shapes that were true once and are wrong now. Each is a *derivable* fact — the
# card must state the command that answers it, never the answer itself.
VOLATILE_SHAPES = {
    "asserted-inventory-count": re.compile(
        r"\b\d[\d,]*\+?\s+(?:tools?|tests?|categories|articles|lines|files)\b",
        re.IGNORECASE,
    ),
    "asserted-approximate-timing": re.compile(
        r"~\s*\d+(?:\.\d+)?\s*(?:s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b"
    ),
    "restated-playbook-cap": re.compile(r"\b\d+\s*/\s*\d+\s+cap\b"),
}

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
    findings = [
        f"line {number}: [{shape}] {line.strip()}"
        for number, line in enumerate(card.read_text(encoding="utf-8").splitlines(), start=1)
        for shape, pattern in VOLATILE_SHAPES.items()
        if pattern.search(line)
    ]
    assert not findings, (
        f"{card.parent.name}/{card.name} states a derivable fact that will rot:\n  "
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
