# ABOUTME: Epic Conductor core — parse a cross-repo epic spec and decide the next action.
# ABOUTME: Pure decision engine; GitHub queries and /dispatch are injected edges, not here.
"""The Epic Conductor's decision engine (The Telegraph, design doc §5).

A *conducted epic* is a Nathan-blessed plan that spans repos with ordering
dependencies and a bounded back-and-forth. Its state lives on a GitHub tracking
issue (so a restarted session resumes from the bus, holding none itself); the
spec is a ``telegraph-epic`` YAML block embedded in that issue body.

This module is the **middle-layer service**: given the parsed epic, the live
status of each leg, and how many correction rounds have been spent, it returns
the single next :class:`Decision`. It performs **no** I/O — querying child-issue
state, running ``/dispatch``, and posting to the tracking issue are
the **inner edges**, supplied by the orchestrator that drives this engine. That
split is what keeps the sequencing logic exhaustively testable without GitHub.

The three rails from the design live here:
  - **No leg runs out of order** — a leg is actionable only when every
    ``depends_on`` leg is ``DONE`` (``actionable_legs``).
  - **Bounded back-and-forth** — once ``rounds_used`` reaches ``max_rounds`` the
    engine returns ``HALT_BUDGET`` instead of dispatching more (escalate).
  - **Acceptance is not self-declared** — when all legs are ``DONE`` the engine
    returns ``AWAIT_ACCEPTANCE`` until ``acceptance_met`` is confirmed; only then
    ``COMPLETE``.
  - **Human circuit-breaker** — any ``FAILED``/``NEEDS_INPUT`` leg freezes the
    whole epic (highest priority).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

import yaml


class LegStatus(str, Enum):
    """Live status of a leg, derived by the orchestrator from its child issue/PR."""

    BLOCKED = "blocked"          # dependencies not yet satisfied
    READY = "ready"              # eligible to dispatch
    IN_PROGRESS = "in_progress"  # an agent is working it
    DONE = "done"                # merged / acceptance for this leg met
    FAILED = "failed"            # CI failed or dispatch refused
    NEEDS_INPUT = "needs_input"  # agent blocked on a question


class Action(str, Enum):
    """The single next thing the conductor should do."""

    DISPATCH = "dispatch"                  # run /dispatch on Decision.leg
    FREEZE = "freeze"                      # a leg needs a human; pause the epic
    WAIT = "wait"                          # work in flight, nothing actionable yet
    AWAIT_ACCEPTANCE = "await_acceptance"  # all legs done; confirm criteria
    COMPLETE = "complete"                  # done and accepted
    HALT_BUDGET = "halt_budget"            # back-and-forth budget exhausted; escalate


@dataclass
class Leg:
    id: str
    repo: str
    issue: int | None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Criterion:
    text: str
    checked: bool = False


@dataclass
class Epic:
    id: str
    title: str
    legs: list[Leg]
    acceptance: list[Criterion] = field(default_factory=list)
    max_rounds: int = 3


@dataclass
class Decision:
    action: Action
    leg: Leg | None = None
    reason: str = ""


# --- parsing --------------------------------------------------------------

_FENCE = re.compile(r"```(?:ya?ml)?\s*\n(.*?)```", re.DOTALL)
_FROZEN = (LegStatus.FAILED, LegStatus.NEEDS_INPUT)
_DONE_EXCLUDED = (LegStatus.DONE, LegStatus.IN_PROGRESS, LegStatus.FAILED, LegStatus.NEEDS_INPUT)


def parse_epic(issue_body: str) -> Epic:
    """Extract and validate the ``telegraph-epic`` block from a tracking issue body.

    Raises ``ValueError`` if no block is found, a leg id repeats, a dependency
    names an unknown leg, or the dependency graph contains a cycle.
    """
    spec = _find_epic_block(issue_body)
    epic_id = str(spec["id"])
    legs = [_leg_from_dict(item) for item in spec.get("legs", [])]
    _validate_legs(legs)
    acceptance = [Criterion(text=str(t)) for t in spec.get("acceptance", [])]
    return Epic(
        id=epic_id,
        title=str(spec.get("title", epic_id)),
        legs=legs,
        acceptance=acceptance,
        max_rounds=int(spec.get("max_rounds", 3)),
    )


def _find_epic_block(body: str) -> dict:
    for match in _FENCE.finditer(body):
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "telegraph-epic" in data:
            block = data["telegraph-epic"]
            if isinstance(block, dict):
                return block
    raise ValueError("no `telegraph-epic` YAML block found in the issue body")


def _leg_from_dict(item: dict) -> Leg:
    issue = item.get("issue")
    return Leg(
        id=str(item["id"]),
        repo=str(item["repo"]),
        issue=int(issue) if issue is not None else None,
        depends_on=[str(d) for d in item.get("depends_on", [])],
    )


def _validate_legs(legs: list[Leg]) -> None:
    ids = [leg.id for leg in legs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate leg id in epic spec")
    known = set(ids)
    for leg in legs:
        for dep in leg.depends_on:
            if dep not in known:
                raise ValueError(f"leg {leg.id!r} depends on unknown leg {dep!r}")
    _assert_acyclic(legs)


def _assert_acyclic(legs: list[Leg]) -> None:
    deps = {leg.id: list(leg.depends_on) for leg in legs}
    state: dict[str, int] = {}  # 0=visiting, 1=done

    def visit(node: str) -> None:
        if state.get(node) == 1:
            return
        if state.get(node) == 0:
            raise ValueError(f"dependency cycle through leg {node!r}")
        state[node] = 0
        for dep in deps[node]:
            visit(dep)
        state[node] = 1

    for leg in legs:
        visit(leg.id)


# --- decision engine ------------------------------------------------------


def _status(status: dict[str, LegStatus], leg_id: str) -> LegStatus:
    return status.get(leg_id, LegStatus.BLOCKED)


def actionable_legs(epic: Epic, status: dict[str, LegStatus]) -> list[Leg]:
    """Legs eligible to dispatch now: not already running/done/frozen, deps all DONE.

    Returned in spec order, so the conductor dispatches deterministically.
    """
    out: list[Leg] = []
    for leg in epic.legs:
        if _status(status, leg.id) in _DONE_EXCLUDED:
            continue
        if all(_status(status, dep) == LegStatus.DONE for dep in leg.depends_on):
            out.append(leg)
    return out


def next_decision(
    epic: Epic,
    status: dict[str, LegStatus],
    rounds_used: int = 0,
    *,
    acceptance_met: bool = False,
) -> Decision:
    """Decide the single next action for the epic. Pure; no side effects.

    Priority order (rails from the design): human circuit-breaker > completion >
    budget ceiling > dispatch next actionable leg > wait.
    """
    # 1. Human circuit-breaker — any frozen leg pauses the whole epic.
    for leg in epic.legs:
        if _status(status, leg.id) in _FROZEN:
            return Decision(Action.FREEZE, leg=leg, reason=f"{leg.id} is {_status(status, leg.id).value}")

    # 2. Completion — all legs done; acceptance is confirmed by the conductor, not the legs.
    if epic.legs and all(_status(status, leg.id) == LegStatus.DONE for leg in epic.legs):
        if acceptance_met:
            return Decision(Action.COMPLETE, reason="all legs done and acceptance confirmed")
        return Decision(Action.AWAIT_ACCEPTANCE, reason="all legs done; awaiting acceptance confirmation")

    # 3. Budget ceiling — back-and-forth corrections capped; escalate instead of looping.
    if rounds_used >= epic.max_rounds:
        return Decision(Action.HALT_BUDGET, reason=f"{rounds_used}/{epic.max_rounds} correction rounds used")

    # 4. Dispatch the next actionable leg (spec order).
    ready = actionable_legs(epic, status)
    if ready:
        return Decision(Action.DISPATCH, leg=ready[0], reason="dependencies satisfied")

    # 5. Work is in flight but nothing is actionable yet.
    return Decision(Action.WAIT, reason="awaiting in-flight legs")
