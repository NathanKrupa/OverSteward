# ABOUTME: Holds the review doctrine to the assembler's delta round after a passing verdict (OS#564).
# ABOUTME: No card or reference may still say a pass earns no delta round, or a BLOCK is required.

"""The prose that tells authors how the review loop works, held to the assembler.

Before OS#564 the assembler refused any re-review after a `PASS` or
`PASS-WITH-FINDINGS`, so the cards told authors to list a commit the
post-review `make verify` forced in the PR body instead. The assembler now
accepts that delta round, and the PR-body list is the record rather than the
control. A card still saying "there is no delta round to run" would send an
author down the unreviewed path the ruling closed, so the old forms are
forbidden everywhere the loop is described — and a prohibition only holds if
the same documents also state the rule that replaced it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PR_WORKFLOW = REPO_ROOT / "shared" / "references" / "pr-workflow.md"
REVIEWER_BRIEFS = (
    REPO_ROOT / "shared" / "agents" / "adversarial-reviewer.md",
    REPO_ROOT / ".claude" / "agents" / "adversarial-reviewer.md",
)

#: The forms the assembler no longer keeps, matched with wraps closed.
STALE_FORMS = (
    re.compile(r"re-reviews only after a `BLOCK`"),
    re.compile(r"there is no delta round to run"),
    re.compile(r"only a `?BLOCK`? earns a re-review"),
    re.compile(r"a `PASS-WITH-FINDINGS` earns no re-review"),
    re.compile(r"well-formed `BLOCK` verdict"),
    re.compile(r"must parse as a `BLOCK` verdict"),
    re.compile(r"OS#564 decides"),
)

#: What the reviewer brief and the workflow must say in its place.
DELTA_AFTER_A_PASS = "A commit your passing verdict did not ask for gets a delta round."
WORKFLOW_RULE = "Listing such a commit in the PR body is the record, not the control (OS#564)"
PRE_ROUND_SEQUENCE_CARDS = ("aigranthelper-dev.md", "grantspider-dev.md")
CARD_RULE = "the list is the record, the delta round is the control (OS#564)"


def _prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _loop_documents() -> list[Path]:
    cards = sorted((REPO_ROOT / "shared" / "agents").glob("*.md"))
    cards += sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))
    return [PR_WORKFLOW, *cards]


def test_there_are_loop_documents_to_check() -> None:
    """A parametrized guard over an empty glob passes vacuously."""
    documents = _loop_documents()
    assert PR_WORKFLOW in documents and len(documents) > 2


@pytest.mark.parametrize(
    "document",
    _loop_documents(),
    ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}/{p.name}",
)
def test_no_document_still_says_a_passing_verdict_earns_no_delta_round(document: Path) -> None:
    prose = _prose(document)
    stale = [form.pattern for form in STALE_FORMS if form.search(prose)]
    assert not stale, (
        f"{document.relative_to(REPO_ROOT)} still states a rule the assembler no "
        f"longer keeps (OS#564): {stale}"
    )


def test_the_workflow_states_the_delta_round_after_a_pass() -> None:
    assert WORKFLOW_RULE in _prose(PR_WORKFLOW)


@pytest.mark.parametrize(
    "brief", REVIEWER_BRIEFS, ids=lambda p: f"{p.parent.parent.name}/{p.name}"
)
def test_the_reviewer_brief_states_the_delta_round_after_a_pass(brief: Path) -> None:
    assert DELTA_AFTER_A_PASS in _prose(brief)


@pytest.mark.parametrize(
    "card",
    [
        REPO_ROOT / directory / "agents" / name
        for name in PRE_ROUND_SEQUENCE_CARDS
        for directory in ("shared", ".claude")
    ],
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_a_full_gate_card_sends_its_forced_commit_to_a_delta_round(card: Path) -> None:
    prose = _prose(card)
    assert CARD_RULE in prose
    assert "--since <the sha the last round read>" in prose
