# ABOUTME: Pins the public-repo rule for the reviewer's narrative in the brief, playbook and card.
# ABOUTME: A private issue is named by number only; a public PR body takes the narrative after a read.

"""The reviewer's narrative and a public PR body (OS#765).

The adversarial reviewer can read private repos' issues, and the author pastes
its output into the PR body. In a public repo that body is public. The brief
says the narrative names private issues by number only; the playbook says the
author pastes the verdict block verbatim and the narrative only after reading
it against that rule; OverSteward's own card, the one public dispatch target,
says the same at its paste line. The assembler's header names the brief's
section, so the section heading is pinned against the header's own text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from oversteward.review_input import PUBLIC_REPO_RULE

REPO_ROOT = Path(__file__).resolve().parents[1]

REVIEWER_BRIEFS = (
    REPO_ROOT / "shared" / "agents" / "adversarial-reviewer.md",
    REPO_ROOT / ".claude" / "agents" / "adversarial-reviewer.md",
)
PLAYBOOKS = (
    REPO_ROOT / "shared" / "skills" / "dispatch" / "playbook.md",
    REPO_ROOT / ".claude" / "skills" / "dispatch" / "playbook.md",
)
OVERSTEWARD_CARDS = (
    REPO_ROOT / "shared" / "agents" / "oversteward-dev.md",
    REPO_ROOT / ".claude" / "agents" / "oversteward-dev.md",
)

#: The brief's rule, as the issue states it.
BRIEF_RULE = "the narrative names private issues by number only and never restates their contents"
BRIEF_UNSURE = "When you cannot tell whether a repo is private, treat it as private."
BRIEF_TRIGGER = "Whenever the header carries the `PUBLIC-REPO RULE` line"

#: The playbook's rule: the block verbatim, the narrative only after a read.
PLAYBOOK_RULE = (
    "In a public repo, the PR body takes the reviewer's verdict block verbatim, and its "
    "narrative only after you have read it."
)
PLAYBOOK_UNREAD = "a visibility it could not read is stamped `UNREAD` and treated as public"
PLAYBOOK_WITHHELD = (
    "say in the PR body that a line of the reviewer's narrative was withheld because it "
    "restated a private issue, never what the line said"
)

#: OverSteward's paste line, conditioned on the read.
CARD_CONDITION = "This repo is public, so the findings go beneath it only after you have read"
UNCONDITIONAL_PASTE = "heading, with its findings beneath it."


def _prose(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _id(path: Path) -> str:
    return f"{path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("brief", REVIEWER_BRIEFS, ids=_id)
def test_the_brief_keeps_private_issues_to_their_numbers(brief: Path) -> None:
    prose = _prose(brief)
    for phrase in (BRIEF_RULE, BRIEF_UNSURE, BRIEF_TRIGGER):
        assert phrase in prose, f"{_id(brief)} lacks: {phrase!r}"


def test_the_header_names_a_section_the_brief_has() -> None:
    section = re.search(r"reviewer brief § ([^)]+)\)", PUBLIC_REPO_RULE)
    assert section is not None, PUBLIC_REPO_RULE
    headings = REVIEWER_BRIEFS[0].read_text(encoding="utf-8").splitlines()
    assert f"## {section.group(1)}" in headings


@pytest.mark.parametrize("playbook", PLAYBOOKS, ids=_id)
def test_the_playbook_pastes_the_narrative_only_after_a_read(playbook: Path) -> None:
    prose = _prose(playbook)
    for phrase in (PLAYBOOK_RULE, PLAYBOOK_UNREAD, PLAYBOOK_WITHHELD):
        assert phrase in prose, f"{_id(playbook)} lacks: {phrase!r}"


@pytest.mark.parametrize("card", OVERSTEWARD_CARDS, ids=_id)
def test_the_oversteward_card_conditions_its_paste_on_the_read(card: Path) -> None:
    prose = _prose(card)
    assert CARD_CONDITION in prose
    assert UNCONDITIONAL_PASTE not in prose, (
        f"{_id(card)} still pastes the findings unconditionally into a public PR body"
    )
