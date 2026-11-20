# ABOUTME: Pins the reviewer catalogue's row for writes that grant something (brief, pr-workflow).
# ABOUTME: The reviewer and the author's pre-round-1 pass both name the fact authorizing a grant.

"""The catalogue row for every write that grants access, a plan, a seat, a role or credit.

The reviewer brief's catalogue had enumerations only for destructive
statements. A write that grants something fails the other way: nothing is lost,
something is given to someone the authorizing fact never covered. The row asks,
for each such write, for the fact that authorizes it, one negative fixture in
which that fact is absent, and the mutant that kills it. The author runs the
same row before round 1 (`pr-workflow.md`), so both documents must state it,
and the brief's closing note on what the author runs must name it too. Each
`*-dev` card restates that pass for its own repo, so each card names the row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PR_WORKFLOW = REPO_ROOT / "shared" / "references" / "pr-workflow.md"
REVIEWER_BRIEFS = (
    REPO_ROOT / "shared" / "agents" / "adversarial-reviewer.md",
    REPO_ROOT / ".claude" / "agents" / "adversarial-reviewer.md",
)

#: The row, as both documents state it (wraps closed; the workflow's bullets
#: carry no closing full stop, so the row is matched without one).
GRANT_ROW = (
    "For every write that grants access, a plan, a seat, a role or credit: name the "
    "external fact that authorizes it (a payment status, a verified signature, a role "
    "check), one negative fixture in which that fact is absent, and the mutant that kills it"
)

#: The brief's class for a grant that reaches its write without that fact.
GRANT_HOLE = "A write that grants without that fact on its path is a `hole`."

#: The same class, where the brief lists what earns a `BLOCK`.
GRANT_BLOCK = (
    "or a write grants without the fact that authorizes it. Anything where merging ships a hole."
)

#: The brief's closing note on the author's own pre-round-1 pass.
AUTHOR_PASS = "the destructive path enumeration (#13, #14), the grant enumeration (#15)"


def _prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("brief", REVIEWER_BRIEFS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_reviewer_catalogue_carries_the_grant_row(brief: Path) -> None:
    prose = _prose(brief)
    assert GRANT_ROW in prose, f"{brief} lacks the catalogue row for writes that grant"
    assert GRANT_HOLE in prose, f"{brief} does not class an unauthorized grant as a hole"
    assert GRANT_BLOCK in prose, f"{brief} does not list an unauthorized grant among BLOCKs"


@pytest.mark.parametrize("brief", REVIEWER_BRIEFS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_reviewer_expects_the_author_to_have_run_the_grant_row(brief: Path) -> None:
    assert AUTHOR_PASS in _prose(brief), (
        f"{brief} tells the reviewer the author ran only the destructive entries"
    )


#: Every dispatch agent's card, found by glob so a card added later is covered
#: without editing this file. Seven cards exist, one per dispatch target.
DEV_CARDS = tuple(sorted((REPO_ROOT / "shared" / "agents").glob("*-dev.md")))

#: The opening of each card's restatement of the author's pre-round-1 pass.
CARD_STEP = "- **Before round 1, run the reviewer's catalogue yourself**"

#: The brief entries that step names, and the grant row it states beside them.
CARD_ENTRIES = "(brief entries 13, 14 and 15)"
CARD_GRANT_CLAUSE = "for every write that grants access, a plan, a seat, a role or credit"


def _card_step(card: Path) -> str:
    """The catalogue step's prose: its first line up to the next blank line."""
    lines = card.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(CARD_STEP)]
    assert len(starts) == 1, f"{card} carries {len(starts)} pre-round-1 catalogue steps, not 1"
    step: list[str] = []
    for line in lines[starts[0] :]:
        if not line.strip():
            break
        step.append(line)
    return " ".join(" ".join(step).split())


def test_the_dev_card_glob_finds_every_card() -> None:
    names = {card.name for card in DEV_CARDS}
    assert len(names) == len(DEV_CARDS) >= 7, f"the glob found {sorted(names)}"


@pytest.mark.parametrize("card", DEV_CARDS, ids=lambda p: p.stem)
def test_each_dev_card_names_the_grant_row_beside_the_destructive_entries(card: Path) -> None:
    step = _card_step(card)
    assert CARD_ENTRIES in step, f"{card.name}'s catalogue step does not name entry 15"
    assert CARD_GRANT_CLAUSE in step, f"{card.name}'s catalogue step omits the grant row"


def test_the_pre_round_1_list_carries_the_grant_row() -> None:
    bullet = next(
        line
        for line in PR_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if line.startswith("- **Before round 1, run the reviewer's own catalogue yourself")
    )
    assert GRANT_ROW in " ".join(bullet.split()), (
        "pr-workflow.md's pre-round-1 catalogue bullet lacks the row for writes that grant"
    )
