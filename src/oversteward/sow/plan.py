# ABOUTME: MIDDLE service — classifies every canonical family member per repo and rules on the gates.
# ABOUTME: Pure: every input is already observed, so a gate test needs no git, no gh and no network.

"""What sow would do, decided before anything is written.

Two ideas carry the module.

**Drift has a direction, and canon's own history is what reveals it.** A repo
copy equal to *any* blob the canonical member has ever carried was deployed from
canon and left behind — redeploying it destroys nothing. A copy equal to none of
them was edited downstream, and overwriting it would erase both a possible
deliberate hotfix and the only evidence of a byte-copy ratchet-treaty breach.
That is the whole reason the classification is three-way rather than a hash
mismatch: `stale` and `diverged` have identical hashes and opposite meanings.

**Absence is two states, not one.** A member the repo's own `CLAUDE.md` already
tells agents to run, which is not on origin, is a broken instruction — deploy
it. A member nothing references has simply not been adopted here, and adoption
is a registry decision, never a side effect of a sync run.

Every gate returns a verdict rather than raising, because one context's failure
must abort that context alone and still be reportable at the end. The verdicts
are deliberately three-valued: `blocked` is a measured answer ("we looked, and
the answer is no"), while `unreadable` means we could not look at all — the
distinction the exit codes are built on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..dev_family import deployed_relpath

IDENTICAL = "identical"
STALE = "stale"
DIVERGED = "diverged"
MISSING = "missing"
NOT_ADOPTED = "absent-not-adopted"

#: The only two statuses sow ever writes. `diverged` is flagged, `identical` is
#: a no-op, and `absent-not-adopted` is left alone — sow is additive.
DEPLOYABLE_STATUSES = frozenset({STALE, MISSING})

PASS = "pass"
BLOCKED = "blocked"
UNREADABLE = "unreadable"
NOT_APPLICABLE = "n/a"

SYNC_BRANCH_PREFIX = "oversteward/sync-"

#: The exclusion a target repo needs before a canonical member can survive its
#: formatter (OVERSTEWARD.md § "Byte-identity requires formatter exclusion").
#: sow never edits a consumer's pyproject; it prints what that repo's own PR owes.
EXCLUSION_HINT = (
    "[tool.ruff] extend-exclude = "
    '["scripts/dev/", ".claude/hooks/", "tests/dev/"] and force-exclude = true'
)

G1 = "G1"
G2 = "G2"
G3 = "G3"
G4 = "G4"
G7 = "G7"
G8 = "G8"
G9 = "G9"


@dataclass(frozen=True)
class Gate:
    """One pre-condition's answer. `blocked` was measured; `unreadable` was not."""

    gate: str
    verdict: str
    detail: str

    @property
    def blocking(self) -> bool:
        return self.verdict in (BLOCKED, UNREADABLE)


@dataclass(frozen=True)
class MemberPlan:
    member: str
    relpath: str
    status: str
    canonical_blob: str
    deployed_blob: str | None


@dataclass(frozen=True)
class ContextObservation:
    """One repo as it stands on its registry branch, already read."""

    context_id: str
    branch: str
    repo_root: str | None
    skip_sow: bool
    readable: bool
    doctrine_text: str = ""
    deployed: Mapping[str, str | None] | None = None
    open_sync_branches: tuple[str, ...] | None = ()


@dataclass(frozen=True)
class ContextPlan:
    context_id: str
    branch: str
    sync_branch: str
    repo_root: str | None
    gates: tuple[Gate, ...]
    members: tuple[MemberPlan, ...]

    @property
    def deployable(self) -> tuple[MemberPlan, ...]:
        return tuple(m for m in self.members if m.status in DEPLOYABLE_STATUSES)

    @property
    def diverged(self) -> tuple[MemberPlan, ...]:
        return tuple(m for m in self.members if m.status == DIVERGED)

    @property
    def blocking_gate(self) -> Gate | None:
        return next((gate for gate in self.gates if gate.blocking), None)


@dataclass(frozen=True)
class SowPlan:
    date: str
    apply_requested: bool
    contexts: tuple[ContextPlan, ...]
    without_checkout: tuple[str, ...]
    members_checked: int


def sync_branch_for(date: str) -> str:
    return f"{SYNC_BRANCH_PREFIX}{date}"


def classify_member_status(
    canonical_blob: str,
    deployed_blob: str | None,
    history_blobs: Iterable[str],
    doctrine_referenced: bool,
) -> str:
    """One member's state in one repo, from canon's history rather than a baseline file."""
    if deployed_blob is None:
        return MISSING if doctrine_referenced else NOT_ADOPTED
    if deployed_blob == canonical_blob:
        return IDENTICAL
    return STALE if deployed_blob in frozenset(history_blobs) else DIVERGED


def gate_origin_readable(readable: bool, branch: str) -> Gate:
    """G1 — the branch sow would branch from can be read.

    Replaces the pinned contract's clean-tree check: sow branches a throwaway
    worktree off ``origin/<branch>`` and never touches the resident checkout's
    working tree, so cleanliness is structural. What can still fail is the read.
    """
    if readable:
        return Gate(G1, PASS, f"origin/{branch} readable")
    return Gate(G1, UNREADABLE, f"origin/{branch} could not be read — nothing was measured here")


def gate_no_stacked_pr(open_sync_branches: Sequence[str] | None) -> Gate:
    """G2 — no prior sync PR is already open on the target. Fails closed."""
    if open_sync_branches is None:
        return Gate(G2, UNREADABLE, "open pull requests could not be listed — refusing to stack")
    if open_sync_branches:
        return Gate(G2, BLOCKED, f"prior sync PR open on {', '.join(open_sync_branches)}")
    return Gate(G2, PASS, "no open oversteward/sync-* pull request")


def gate_context_registered(context_id: str, registered_ids: Iterable[str]) -> Gate:
    """G3 — the id names a context registry.yaml actually carries."""
    if context_id in frozenset(registered_ids):
        return Gate(G3, PASS, f"{context_id} is registered")
    return Gate(G3, UNREADABLE, f"unknown context id '{context_id}' — not in registry.yaml")


def gate_not_skip_sow(skip_sow: bool) -> Gate:
    """G4 — the context has not opted out of governance writes."""
    if skip_sow:
        return Gate(G4, BLOCKED, "context carries skip_sow: true — skipped by design")
    return Gate(G4, PASS, "skip_sow absent")


def gate_explicit_apply(apply_requested: bool) -> Gate:
    """G8 — writing is opt-in. The default run measures and writes nothing."""
    if apply_requested:
        return Gate(G8, PASS, "--apply given")
    return Gate(G8, BLOCKED, "dry run — pass --apply to write")


def gate_lock(acquired: bool, lock_path: str) -> Gate:
    """G7 — one sow run at a time on this machine."""
    if acquired:
        return Gate(G7, PASS, f"holding {lock_path}")
    return Gate(G7, UNREADABLE, f"another sow run holds {lock_path}")


def gate_consumer_format(
    ruff_available: bool, objections: Sequence[str], relpaths: Sequence[str]
) -> Gate:
    """G9 — the TARGET repo's own ruff must not object to the bytes about to land.

    An objection means that repo never took the OS#241 exclusion, so its own
    formatter would rewrite the copy in the deploy commit and drift it on
    arrival. sow aborts the context and names what the repo's own PR owes; it
    never edits a consumer's pyproject.
    """
    if not ruff_available:
        return Gate(G9, NOT_APPLICABLE, "target repo has no .venv/bin/ruff — no formatter to object")
    if objections:
        named = "; ".join(objections)
        return Gate(
            G9,
            BLOCKED,
            f"target ruff objects to {', '.join(relpaths)}: {named}. "
            f"That repo needs {EXCLUSION_HINT} before the family can deploy byte-identical.",
        )
    return Gate(G9, PASS, f"target ruff accepts {len(relpaths)} copied file(s)")


def _context_gates(
    observation: ContextObservation, apply_requested: bool, registered_ids: Iterable[str]
) -> tuple[Gate, ...]:
    return (
        gate_context_registered(observation.context_id, registered_ids),
        gate_not_skip_sow(observation.skip_sow),
        gate_origin_readable(observation.readable, observation.branch),
        gate_no_stacked_pr(observation.open_sync_branches),
        gate_explicit_apply(apply_requested),
    )


def _context_members(
    observation: ContextObservation,
    canonical: Mapping[str, str],
    history: Mapping[str, frozenset[str]],
) -> tuple[MemberPlan, ...]:
    if not observation.readable:
        return ()
    deployed = observation.deployed or {}
    return tuple(
        MemberPlan(
            member=member,
            relpath=deployed_relpath(member),
            status=classify_member_status(
                blob,
                deployed.get(member),
                history.get(member, frozenset()),
                member in observation.doctrine_text,
            ),
            canonical_blob=blob,
            deployed_blob=deployed.get(member),
        )
        for member, blob in sorted(canonical.items())
    )


def _unknown_context(context_id: str, date: str, registered_ids: Iterable[str]) -> ContextPlan:
    return ContextPlan(
        context_id=context_id,
        branch="",
        sync_branch=sync_branch_for(date),
        repo_root=None,
        gates=(gate_context_registered(context_id, registered_ids),),
        members=(),
    )


def plan(
    observations: Sequence[ContextObservation],
    canonical: Mapping[str, str],
    history: Mapping[str, frozenset[str]],
    *,
    date: str,
    apply_requested: bool,
    registered_ids: Iterable[str],
    requested_ids: Sequence[str] = (),
    without_checkout: Sequence[str] = (),
) -> SowPlan:
    """Every context's member classification and gate verdicts. No I/O, no writes."""
    known = frozenset(registered_ids)
    contexts = [
        ContextPlan(
            context_id=observation.context_id,
            branch=observation.branch,
            sync_branch=sync_branch_for(date),
            repo_root=observation.repo_root,
            gates=_context_gates(observation, apply_requested, known),
            members=_context_members(observation, canonical, history),
        )
        for observation in observations
    ]
    contexts.extend(
        _unknown_context(requested, date, known) for requested in requested_ids if requested not in known
    )
    return SowPlan(
        date=date,
        apply_requested=apply_requested,
        contexts=tuple(contexts),
        without_checkout=tuple(without_checkout),
        members_checked=len(canonical),
    )


DEPLOYED = "deployed"
NO_OP = "no-op"
SKIPPED = "skipped"
ABORTED = "aborted"
UNREADABLE_CONTEXT = "unreadable"

#: Exit codes carry meaning and must not be collapsed. 0 is a measured answer —
#: a printed plan, or an apply that ran; 1 means a write step sow attempted
#: failed; 2 means it could not look at all (no registry, no canon, the lock
#: held, an unreadable origin). "Nothing to do" is 0 and says so in words.
#: An aborted write outranks an unreadable context because the operator asked
#: for a write and did not get one; the report names both either way.
EXIT_MEASURED = 0
EXIT_APPLY_FAILED = 1
EXIT_COULD_NOT_LOOK = 2


@dataclass(frozen=True)
class ContextOutcome:
    context_id: str
    action: str
    members: tuple[str, ...]
    detail: str
    pr_url: str | None = None
    shas: Mapping[str, Mapping[str, str | None]] | None = None


@dataclass(frozen=True)
class SowReport:
    date: str
    applied: bool
    outcomes: tuple[ContextOutcome, ...]
    members_checked: int
    contexts_checked: int
    without_checkout: tuple[str, ...]


@dataclass(frozen=True)
class SharedDeployResult:
    target: str
    copied: int
    skipped: int
    unchanged: int
    reachable: bool


def exit_code(report: SowReport) -> int:
    """One code for the whole run. See the EXIT_* constants for the precedence."""
    actions = {outcome.action for outcome in report.outcomes}
    if ABORTED in actions:
        return EXIT_APPLY_FAILED
    if UNREADABLE_CONTEXT in actions:
        return EXIT_COULD_NOT_LOOK
    return EXIT_MEASURED
