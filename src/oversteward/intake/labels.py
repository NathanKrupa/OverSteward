# ABOUTME: The dispatch label taxonomy — every label /dispatch, intake and the queue read — as data.
# ABOUTME: ensure_labels upserts it on each repository through an injected upsert call.

"""The labels the dispatch pipeline reads, written down once.

``scripts/orchestration/setup_dispatch_labels.sh`` creates them on every
repository it is pointed at. ``gh label create --force`` is an upsert, so a
re-run updates a label's colour and description rather than failing on it.

Intake labels (OS#613, Nathan 2026-10-21):

* ``tribe`` — a food-pantry user of AI Grant Helper would notice it (PLDP
  Goal 8). It outranks every other issue, a paying consulting client's ask
  included, "for now".
* ``agent-finding`` — filed by an agent rather than asked for by Nathan.
* ``shelved`` — an issue holding one of Nathan's ideas, retired without being
  worked (OS#612). The verb is "shelve", never "kill". An idea that lives only
  in the Estate Idea Incubator note is shelved in the note, not by this label.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

TRIBE = "tribe"
AGENT_FINDING = "agent-finding"
SHELVED = "shelved"

READY_FOR_AGENT = "ready-for-agent"
NEEDS_SCOPING = "needs-scoping"
NEEDS_INPUT = "needs-input"
AGENT_IN_PROGRESS = "agent-in-progress"
REJECT_CLOSE = "reject-close"
DISPATCH_PAUSED = "dispatch-paused"


@dataclass(frozen=True, slots=True)
class LabelSpec:
    name: str
    color: str
    description: str


DISPATCH_LABELS: tuple[LabelSpec, ...] = (
    LabelSpec(READY_FOR_AGENT, "0E8A16", "Scoped with acceptance — can dispatch"),
    LabelSpec(NEEDS_SCOPING, "FBCA04", "Requires Nathan to scope before dispatch"),
    LabelSpec(NEEDS_INPUT, "D93F0B", "Agent waiting on Nathan's answer"),
    LabelSpec(AGENT_IN_PROGRESS, "5319E7", "Agent actively working (auto-applied)"),
    LabelSpec(REJECT_CLOSE, "CFD3D7", "Triaged as bad/obsolete"),
    LabelSpec(
        DISPATCH_PAUSED,
        "B60205",
        "Kill-switch — /dispatch refuses the repo while any open issue has this label",
    ),
    LabelSpec(TRIBE, "0052CC", "A food-pantry user of AI Grant Helper would notice it — ranks first"),
    LabelSpec(AGENT_FINDING, "BFD4F2", "Filed by an agent, not asked for by Nathan"),
    LabelSpec(SHELVED, "D4C5F9", "Holds one of Nathan's ideas, shelved without being worked"),
)

Upsert = Callable[[str, LabelSpec], object]


def ensure_labels(
    repos: Iterable[str], upsert: Upsert, specs: Iterable[LabelSpec] = DISPATCH_LABELS
) -> list[tuple[str, str, str]]:
    """Upsert every label on every repository; return ``(repo, label, error)`` per failure.

    A failure on one label does not stop the rest: a run that halted at the
    first 403 would leave every later repository silently unlabelled.
    """
    specs = tuple(specs)
    failures: list[tuple[str, str, str]] = []
    for repo in repos:
        for spec in specs:
            try:
                upsert(repo, spec)
            except Exception as exc:  # noqa: BLE001 — every failure is reported, none swallowed
                failures.append((repo, spec.name, str(exc)))
    return failures
