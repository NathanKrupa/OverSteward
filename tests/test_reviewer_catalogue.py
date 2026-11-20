# ABOUTME: Pins the reviewer catalogue's row for writes that grant something, in the brief and pr-workflow.
# ABOUTME: Both the reviewer and the author's pre-round-1 pass must name the fact that authorizes a grant.

"""The catalogue row for every write that grants access, a plan, a seat, a role or credit.

The reviewer brief's catalogue had enumerations only for destructive
statements. A write that grants something fails the other way: nothing is lost,
something is given to someone the authorizing fact never covered. The row asks,
for each such write, for the fact that authorizes it, one negative fixture in
which that fact is absent, and the mutant that kills it. The author runs the
same row before round 1 (`pr-workflow.md`), so both documents must state it,
and the brief's closing note on what the author runs must name it too.
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

#: The brief's closing note on the author's own pre-round-1 pass.
AUTHOR_PASS = "the destructive path enumeration (#13, #14), the grant enumeration (#15)"


def _prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("brief", REVIEWER_BRIEFS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_reviewer_catalogue_carries_the_grant_row(brief: Path) -> None:
    prose = _prose(brief)
    assert GRANT_ROW in prose, f"{brief} lacks the catalogue row for writes that grant"
    assert GRANT_HOLE in prose, f"{brief} does not class an unauthorized grant as a hole"


@pytest.mark.parametrize("brief", REVIEWER_BRIEFS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_reviewer_expects_the_author_to_have_run_the_grant_row(brief: Path) -> None:
    assert AUTHOR_PASS in _prose(brief), (
        f"{brief} tells the reviewer the author ran only the destructive entries"
    )


def test_the_pre_round_1_list_carries_the_grant_row() -> None:
    bullet = next(
        line
        for line in PR_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if line.startswith("- **Before round 1, run the reviewer's own catalogue yourself")
    )
    assert GRANT_ROW in " ".join(bullet.split()), (
        "pr-workflow.md's pre-round-1 catalogue bullet lacks the row for writes that grant"
    )
