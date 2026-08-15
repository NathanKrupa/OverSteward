# ABOUTME: Tests for the Epic Conductor core — epic-spec parsing + the pure decision engine.
# ABOUTME: No GitHub/dispatch I/O here; those are injected edges. This proves the sequencing logic.

from __future__ import annotations

import pytest

from oversteward.telegraph import conductor as c
from oversteward.telegraph.conductor import Action, LegStatus

# --- a small reusable epic spec (GS->AG funder_ein, the design's worked example) ---

EPIC_BODY = """
Some preamble describing the epic for humans.

```yaml
telegraph-epic:
  id: funder-ein
  title: expose funder_ein end-to-end
  max_rounds: 3
  acceptance:
    - GS research schema exposes funder_ein
    - AG reader returns funder_ein
  legs:
    - {id: leg1, repo: grantspider, issue: 201, depends_on: []}
    - {id: leg2, repo: grantspider, issue: 202, depends_on: [leg1]}
    - {id: leg3, repo: aigranthelper, issue: 305, depends_on: [leg2]}
```

Trailing prose.
"""


# --- parse_epic -----------------------------------------------------------


def test_parse_epic_reads_structure():
    epic = c.parse_epic(EPIC_BODY)
    assert epic.id == "funder-ein"
    assert epic.title == "expose funder_ein end-to-end"
    assert epic.max_rounds == 3
    assert [leg.id for leg in epic.legs] == ["leg1", "leg2", "leg3"]
    assert epic.legs[2].repo == "aigranthelper"
    assert epic.legs[2].issue == 305
    assert epic.legs[1].depends_on == ["leg1"]
    assert [crit.text for crit in epic.acceptance] == [
        "GS research schema exposes funder_ein",
        "AG reader returns funder_ein",
    ]


def test_parse_epic_no_block_raises():
    with pytest.raises(ValueError):
        c.parse_epic("just prose, no epic block")


def test_parse_epic_unknown_dependency_raises():
    body = """
```yaml
telegraph-epic:
  id: x
  title: x
  legs:
    - {id: a, repo: r, issue: 1, depends_on: [nope]}
```
"""
    with pytest.raises(ValueError):
        c.parse_epic(body)


def test_parse_epic_duplicate_leg_id_raises():
    body = """
```yaml
telegraph-epic:
  id: x
  title: x
  legs:
    - {id: a, repo: r, issue: 1, depends_on: []}
    - {id: a, repo: r, issue: 2, depends_on: []}
```
"""
    with pytest.raises(ValueError):
        c.parse_epic(body)


def test_parse_epic_dependency_cycle_raises():
    body = """
```yaml
telegraph-epic:
  id: x
  title: x
  legs:
    - {id: a, repo: r, issue: 1, depends_on: [b]}
    - {id: b, repo: r, issue: 2, depends_on: [a]}
```
"""
    with pytest.raises(ValueError):
        c.parse_epic(body)


def test_parse_epic_defaults_max_rounds():
    body = """
```yaml
telegraph-epic:
  id: x
  title: x
  legs:
    - {id: a, repo: r, issue: 1, depends_on: []}
```
"""
    assert c.parse_epic(body).max_rounds == 3


# --- actionable_legs ------------------------------------------------------


def _epic():
    return c.parse_epic(EPIC_BODY)


def test_actionable_only_dependency_free_leg_at_start():
    epic = _epic()
    status = {"leg1": LegStatus.READY, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    actionable = c.actionable_legs(epic, status)
    assert [leg.id for leg in actionable] == ["leg1"]


def test_dependent_becomes_actionable_when_dep_done():
    epic = _epic()
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    assert [leg.id for leg in c.actionable_legs(epic, status)] == ["leg2"]


def test_in_progress_leg_is_not_re_dispatched():
    epic = _epic()
    status = {"leg1": LegStatus.IN_PROGRESS, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    assert c.actionable_legs(epic, status) == []


# --- next_decision --------------------------------------------------------


def test_decision_dispatches_first_actionable():
    epic = _epic()
    status = {"leg1": LegStatus.READY, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status)
    assert d.action == Action.DISPATCH
    assert d.leg.id == "leg1"


def test_decision_respects_dependency_order():
    epic = _epic()
    # leg1 done, leg2 ready -> must pick leg2, never leg3 (its dep leg2 not done)
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.READY, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status)
    assert d.action == Action.DISPATCH
    assert d.leg.id == "leg2"


def test_decision_freezes_on_needs_input():
    epic = _epic()
    status = {"leg1": LegStatus.NEEDS_INPUT, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status)
    assert d.action == Action.FREEZE
    assert d.leg.id == "leg1"


def test_decision_freezes_on_failure():
    epic = _epic()
    status = {"leg1": LegStatus.FAILED, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    assert c.next_decision(epic, status).action == Action.FREEZE


def test_decision_await_acceptance_when_all_done_unconfirmed():
    epic = _epic()
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.DONE, "leg3": LegStatus.DONE}
    d = c.next_decision(epic, status, acceptance_met=False)
    assert d.action == Action.AWAIT_ACCEPTANCE


def test_decision_complete_when_all_done_and_accepted():
    epic = _epic()
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.DONE, "leg3": LegStatus.DONE}
    d = c.next_decision(epic, status, acceptance_met=True)
    assert d.action == Action.COMPLETE


def test_decision_halts_on_budget_exhaustion():
    epic = _epic()
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.READY, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status, rounds_used=3)
    assert d.action == Action.HALT_BUDGET


def test_decision_waits_when_nothing_actionable_but_work_in_flight():
    epic = _epic()
    status = {"leg1": LegStatus.IN_PROGRESS, "leg2": LegStatus.BLOCKED, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status)
    assert d.action == Action.WAIT


def test_freeze_takes_priority_over_budget_and_completion():
    epic = _epic()
    status = {"leg1": LegStatus.DONE, "leg2": LegStatus.NEEDS_INPUT, "leg3": LegStatus.BLOCKED}
    d = c.next_decision(epic, status, rounds_used=99)
    assert d.action == Action.FREEZE


def test_missing_status_treated_as_blocked():
    epic = _epic()
    # empty status dict: leg1 has no deps so it is actionable; others blocked
    d = c.next_decision(epic, {})
    assert d.action == Action.DISPATCH
    assert d.leg.id == "leg1"
