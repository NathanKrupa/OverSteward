# ABOUTME: MIDDLE service for the abandoned-work sweep — the rules that define "abandoned", and their execution.
# ABOUTME: Dry-run is the default: without apply the writer is never called, and every decision is still ledgered.

"""Decide what across the estate has been abandoned, and shelve it reversibly.

The rules (OverSteward #612), each undone by one comment:

* **Pull request** — no commit, comment or review for :data:`PR_IDLE` and not
  carried: label ``shelved``, comment "shelved — reopen by comment", close. The
  branch is kept. A comment beginning ``carried:`` exempts it at any age.
* **Branch with no pull request** — no commit for :data:`BRANCH_IDLE`: reported,
  never deleted. When its name follows the dispatch convention
  ``<type>/issue-<n>-<slug>`` and issue *n* is open, a close-out note goes on
  that issue once.
* **``agent-finding`` issue** — no update for :data:`FINDING_IDLE`: label
  ``shelved``, comment the reason, close as not planned.
* **Any other issue is never closed.** At :data:`INCUBATOR_IDLE` it becomes a
  candidate for the Estate Brief's one ask ("move to the Incubator?"); the sweep
  only names it.
* **Unlanded worktree** — a linked worktree whose ``HEAD`` is not on the trunk
  and has had no commit for :data:`WORKTREE_IDLE`: reported. Teardown is
  ``worktree_doctor``'s, never this sweep's.
* **Reopen** — a shelved item whose newest comment, posted after it closed,
  begins with ``reopen`` is reopened and loses ``shelved``.

Every comment the sweep posts carries :data:`MARKER` and begins with neither
``reopen`` nor ``carried:``, and a comment carrying the marker is never read as
a reopen, an exemption, or motion — so the sweep cannot trigger itself.

Reading is total before anything is decided: a repository that cannot be read
fails the run, because a sweep missing a repository reports a smaller estate.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from oversteward.board.client import GhError, read_estate
from oversteward.board.config import RepoRef, repos_from_registry
from oversteward.board.models import Issue
from oversteward.shelve.client import (
    AGENT_FINDING,
    SHELVED,
    Branch,
    LinkedIssue,
    OpenPull,
    RepoSnapshot,
    ShelvedItem,
    Thread,
    read_linked_issue,
    read_snapshot,
)
from oversteward.shelve.ledger import MODE_APPLIED, MODE_DRY, LedgerEntry
from oversteward.shelve.worktrees import Worktree

PR_IDLE = timedelta(days=21)
BRANCH_IDLE = timedelta(days=30)
FINDING_IDLE = timedelta(days=60)
INCUBATOR_IDLE = timedelta(days=90)
#: A worktree untouched this long, holding work not on the trunk, is reported.
WORKTREE_IDLE = timedelta(days=7)

#: Every comment the sweep writes carries this; such a comment is never a trigger.
MARKER = "<!-- oversteward:shelve-sweep"
SHELVE_LEAD = "shelved — reopen by comment."

#: ``reopen`` as a whole word at the start: "Reopen — …" reopens, "Reopened as #640" does not.
_REOPEN = re.compile(r"reopen\b", re.IGNORECASE)

#: ``<type>/issue-<n>-<slug>``, the dispatch playbook's branch name.
_BRANCH_ISSUE = re.compile(r"(?:^|/)issue-(\d+)(?:-|$)")

RULE_PR = "pr-idle"
RULE_PR_UNJUDGED = "pr-idle-unjudged"
RULE_FINDING = "finding-idle"
RULE_BRANCH = "branch-no-pr"
RULE_WORKTREE = "worktree-unlanded"
RULE_INCUBATOR = "incubator-candidate"
RULE_REOPEN = "reopen-by-comment"
#: The line each completed run appends last, so a reader can tell "nothing to do" from "did not run".
RULE_RUN = "sweep-run"

VERB_SHELVE = "shelve"
VERB_CLOSE = "close"
VERB_REOPEN = "reopen"
VERB_NOTE = "note"
VERB_REPORT = "report"
VERB_CANDIDATE = "candidate"
VERB_RUN = "run"
#: Ledger action for a write gh did not complete; the attempted verb leads ``reason``.
VERB_FAILED = "failed"

#: Verbs that change GitHub. Only these ever reach the writer.
WRITE_VERBS = frozenset({VERB_SHELVE, VERB_CLOSE, VERB_REOPEN, VERB_NOTE})
#: Verbs that put the ``shelved`` label on, so need it to exist first.
_LABELLING = frozenset({VERB_SHELVE, VERB_CLOSE})

_SAID = {
    MODE_DRY: {VERB_SHELVE: "would shelve", VERB_CLOSE: "would close", VERB_REOPEN: "would reopen",
               VERB_NOTE: "would note"},
    MODE_APPLIED: {VERB_SHELVE: "shelved", VERB_CLOSE: "closed", VERB_REOPEN: "reopened",
                   VERB_NOTE: "noted"},
}


class MissingLabelError(RuntimeError):
    """An apply would add a label the repository does not have; GitHub would create it."""


class Writer(Protocol):
    def shelve_pull(self, repo: RepoRef, number: int, comment: str) -> None: ...
    def close_finding(self, repo: RepoRef, number: int, comment: str) -> None: ...
    def reopen(self, repo: RepoRef, kind: str, number: int) -> None: ...
    def note(self, repo: RepoRef, number: int, comment: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SweepTarget:
    """One repository the sweep covers, with the trunks it must never judge as branches."""

    repo: RepoRef
    trunks: frozenset[str]
    #: The branch work lands on, for the worktree rule.
    trunk: str
    local_path: Path | None


def targets_from_registry(registry: Mapping[str, Any]) -> list[SweepTarget]:
    """Every dispatch-target context, in registry order."""
    contexts = {(c.get("id") or c.get("name")): c for c in registry.get("contexts") or []}
    targets = []
    for ref in repos_from_registry(dict(registry)):
        context = contexts[ref.id]
        trunk = context.get("branch") or "main"
        names = {trunk, context.get("primary_branch") or trunk}
        path = context.get("local_path")
        targets.append(SweepTarget(ref, frozenset(names), trunk, Path(path) if path else None))
    return targets


@dataclass(frozen=True, slots=True)
class Survey:
    """Everything read, before any decision: per repository, plus linked issues and worktrees."""

    snapshots: dict[str, RepoSnapshot]
    linked: dict[tuple[str, int], LinkedIssue | None]
    worktrees: tuple[Worktree, ...]


@dataclass(frozen=True, slots=True)
class Action:
    repo: RepoRef
    kind: str
    number: int | None
    ref: str | None
    title: str
    url: str
    rule: str
    verb: str
    idle_days: int | None
    reason: str
    #: The comment a write posts; ``None`` for actions that post nothing.
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class Failure:
    """A write gh did not complete: ledgered as ``failed``, never as performed."""

    action: Action
    error: str


@dataclass(frozen=True, slots=True)
class Outcome:
    #: Ledgered actions — every action for a dry run; the performed ones for an apply.
    entries: tuple[LedgerEntry, ...]
    failures: tuple[Failure, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    actions: tuple[Action, ...]
    #: Repositories where an apply would need the ``shelved`` label and it does not exist.
    unlabelled: tuple[str, ...]


def own(body: str) -> bool:
    """Whether the sweep wrote this comment."""
    return MARKER in body


def _says(body: str, prefix: str) -> bool:
    return not own(body) and body.lstrip().lower().startswith(prefix)


def _days(span: timedelta) -> int:
    return span // timedelta(days=1)


def linked_issue_number(branch: str) -> int | None:
    match = _BRANCH_ISSUE.search(branch)
    return int(match[1]) if match else None


def note_marker(branch: str) -> str:
    return f"{MARKER} branch={branch} -->"


# --- reading ---------------------------------------------------------------


def survey(
    targets: Sequence[SweepTarget],
    *,
    now: datetime,
    read_repo: Callable[[RepoRef], RepoSnapshot] = read_snapshot,
    read_issue: Callable[[RepoRef, int], LinkedIssue | None] = read_linked_issue,
    read_trees: Callable[[SweepTarget], tuple[Worktree, ...]],
) -> Survey:
    """Read every repository, every stale branch's linked issue, and every worktree."""
    snapshots = read_estate([t.repo for t in targets], reader=read_repo)
    linked: dict[tuple[str, int], LinkedIssue | None] = {}
    for target in targets:
        for branch in _stale_branches(snapshots[target.repo.id], target, now):
            number = linked_issue_number(branch.name)
            if number is not None and (target.repo.id, number) not in linked:
                linked[(target.repo.id, number)] = read_issue(target.repo, number)
    trees = tuple(tree for target in targets for tree in read_trees(target))
    return Survey(snapshots=snapshots, linked=linked, worktrees=trees)


# --- rules -----------------------------------------------------------------


def last_motion(pull: OpenPull) -> datetime:
    """The newest commit, review or comment — the sweep's own comments excluded."""
    times = [pull.created_at, pull.last_commit_at, pull.last_review_at]
    times += [c.created_at for c in pull.thread.comments if not own(c.body)]
    return max(t for t in times if t is not None)


def carried(thread: Thread) -> bool:
    return any(_says(c.body, "carried:") for c in thread.comments)


def wants_reopen(item: ShelvedItem) -> bool:
    """The newest comment came after the close, is not the sweep's, and opens with the word ``reopen``."""
    if not item.thread.comments:
        return False
    newest = max(item.thread.comments, key=lambda c: c.created_at)
    return (
        newest.created_at > item.closed_at
        and not own(newest.body)
        and _REOPEN.match(newest.body.lstrip()) is not None
    )


def _stale_branches(snapshot: RepoSnapshot, target: SweepTarget, now: datetime) -> list[Branch]:
    trunks = target.trunks | {snapshot.default_branch}
    return [
        b
        for b in snapshot.branches
        if not b.has_pull
        and b.name not in trunks
        and b.last_commit_at is not None
        and now - b.last_commit_at >= BRANCH_IDLE
    ]


def _pr_comment(pull: OpenPull, idle: int) -> str:
    return (
        f"{SHELVE_LEAD}\n\nNo commit, comment or review on this pull request for {idle} days, "
        f"so the abandoned-work sweep has closed it. The branch `{pull.branch}` is kept. "
        "To bring it back, comment a line that starts with `reopen`. To keep a waiting "
        "pull request open, comment a line that starts with `carried:` and the reason."
        f"\n\n{MARKER} -->"
    )


def _finding_comment(idle: int) -> str:
    return (
        f"{SHELVE_LEAD}\n\nThis `{AGENT_FINDING}` issue has had no activity for {idle} days, "
        "so the abandoned-work sweep has closed it as not planned. To bring it back, "
        "comment a line that starts with `reopen`."
        f"\n\n{MARKER} -->"
    )


def _note_comment(branch: Branch, idle: int) -> str:
    return (
        f"Close-out note: branch `{branch.name}` has had no commit for {idle} days and never "
        "had a pull request. It is kept, not deleted; the abandoned-work sweep only reports it."
        f"\n\n{note_marker(branch.name)}"
    )


def _pull_actions(repo: RepoRef, pulls: Iterable[OpenPull], now: datetime) -> list[Action]:
    actions = []
    for pull in pulls:
        idle = now - last_motion(pull)
        if idle < PR_IDLE or carried(pull.thread):
            continue
        base = dict(repo=repo, kind="pr", number=pull.number, ref=pull.branch, title=pull.title,
                    url=pull.url, idle_days=_days(idle))
        if not pull.thread.complete:
            actions.append(Action(**base, rule=RULE_PR_UNJUDGED, verb=VERB_REPORT,
                                  reason="over 100 comments: a carried: marker may be unread"))
            continue
        actions.append(Action(**base, rule=RULE_PR, verb=VERB_SHELVE,
                              reason="no commit, comment or review", comment=_pr_comment(pull, _days(idle))))
    return actions


def _issue_actions(repo: RepoRef, issues: Iterable[Issue], now: datetime) -> list[Action]:
    actions = []
    for issue in issues:
        idle = now - issue.updated_at
        base = dict(repo=repo, kind="issue", number=issue.number, ref=None, title=issue.title,
                    url=issue.url, idle_days=_days(idle))
        if AGENT_FINDING in issue.labels:
            if idle >= FINDING_IDLE:
                actions.append(Action(**base, rule=RULE_FINDING, verb=VERB_CLOSE,
                                      reason="agent-finding with no activity",
                                      comment=_finding_comment(_days(idle))))
        elif idle >= INCUBATOR_IDLE:
            actions.append(Action(**base, rule=RULE_INCUBATOR, verb=VERB_CANDIDATE,
                                  reason="move to the Incubator?"))
    return actions


def _branch_actions(
    target: SweepTarget, snapshot: RepoSnapshot, linked: Mapping, now: datetime
) -> list[Action]:
    actions = []
    for branch in _stale_branches(snapshot, target, now):
        idle = _days(now - branch.last_commit_at)
        number = linked_issue_number(branch.name)
        issue = linked.get((target.repo.id, number)) if number is not None else None
        base = dict(repo=target.repo, kind="branch", ref=branch.name, title=branch.name,
                    url=f"https://github.com/{target.repo.full_name}/tree/{branch.name}",
                    rule=RULE_BRANCH, idle_days=idle)
        actions.append(Action(**base, number=None, verb=VERB_REPORT, reason="no pull request"))
        # A cut thread may hold an earlier note out of sight: treat it as noted.
        if issue is not None and issue.open and issue.complete and not any(
            note_marker(branch.name) in body for body in issue.comment_bodies
        ):
            issue_url = f"https://github.com/{target.repo.full_name}/issues/{issue.number}"
            actions.append(Action(**{**base, "kind": "issue", "url": issue_url},
                                  number=issue.number,
                                  verb=VERB_NOTE, reason=f"close-out note for branch {branch.name}",
                                  comment=_note_comment(branch, idle)))
    return actions


def _reopen_actions(repo: RepoRef, items: Iterable[ShelvedItem]) -> list[Action]:
    return [
        Action(repo=repo, kind=item.kind, number=item.number, ref=None, title=item.title,
               url=item.url, rule=RULE_REOPEN, verb=VERB_REOPEN, idle_days=None,
               reason="reopen comment after the shelve")
        for item in items
        if wants_reopen(item)
    ]


def _worktree_actions(
    targets: Sequence[SweepTarget], trees: Iterable[Worktree], now: datetime
) -> list[Action]:
    repos = {t.repo.id: t.repo for t in targets}
    actions = []
    for tree in trees:
        if tree.landed:
            continue
        if tree.missing:
            idle, reason = None, "worktree directory is gone; prune through worktree_doctor"
        elif now - tree.last_commit_at >= WORKTREE_IDLE:
            idle, reason = _days(now - tree.last_commit_at), "HEAD is not on the trunk"
        else:
            continue
        actions.append(Action(repo=repos[tree.repo], kind="worktree", number=None,
                              ref=str(tree.path), title=tree.branch or "(detached)", url="",
                              rule=RULE_WORKTREE, verb=VERB_REPORT, idle_days=idle,
                              reason=reason))
    return actions


def plan(targets: Sequence[SweepTarget], found: Survey, now: datetime) -> Plan:
    """Every action the rules call for, reopenings first."""
    actions: list[Action] = []
    for target in targets:
        snapshot = found.snapshots[target.repo.id]
        actions += _reopen_actions(target.repo, snapshot.shelved)
        actions += _pull_actions(target.repo, snapshot.pulls, now)
        actions += _issue_actions(target.repo, snapshot.issues, now)
        actions += _branch_actions(target, snapshot, found.linked, now)
    actions += _worktree_actions(targets, found.worktrees, now)
    needing = {a.repo.id for a in actions if a.verb in _LABELLING}
    unlabelled = tuple(
        t.repo.id for t in targets
        if t.repo.id in needing and SHELVED not in found.snapshots[t.repo.id].labels
    )
    return Plan(actions=tuple(actions), unlabelled=unlabelled)


# --- execution -------------------------------------------------------------


def _entry(action: Action, mode: str, now: datetime) -> LedgerEntry:
    return LedgerEntry(
        at=now, mode=mode, repo=action.repo.id, kind=action.kind, number=action.number,
        ref=action.ref, title=action.title, url=action.url, rule=action.rule,
        action=action.verb, idle_days=action.idle_days, reason=action.reason,
    )


def run_entry(mode: str, now: datetime, count: int, failed: int = 0) -> LedgerEntry:
    """The closing line of a completed run, written even when it decided nothing."""
    return LedgerEntry(
        at=now, mode=mode, repo="*", kind="run", number=None, ref=None,
        title="abandoned-work sweep", url="", rule=RULE_RUN, action=VERB_RUN, idle_days=None,
        reason=f"{count} actions, {failed} failed",
    )


def _failed_entry(failure: Failure, now: datetime) -> LedgerEntry:
    entry = _entry(failure.action, MODE_APPLIED, now)
    return LedgerEntry(**{**{f: getattr(entry, f) for f in LedgerEntry.__slots__},
                          "action": VERB_FAILED,
                          "reason": f"{failure.action.verb}: {failure.error}"})


def _perform(action: Action, writer: Writer) -> None:
    if action.verb == VERB_SHELVE:
        writer.shelve_pull(action.repo, action.number, action.comment)
    elif action.verb == VERB_CLOSE:
        writer.close_finding(action.repo, action.number, action.comment)
    elif action.verb == VERB_REOPEN:
        writer.reopen(action.repo, action.kind, action.number)
    elif action.verb == VERB_NOTE:
        writer.note(action.repo, action.number, action.comment)


def execute(
    decided: Plan,
    *,
    apply: bool,
    writer: Writer | None,
    record: Callable[[Sequence[LedgerEntry]], None],
    now: datetime,
    refused: tuple[type[Exception], ...] = (GhError,),
) -> Outcome:
    """Ledger every action; perform the writes only when ``apply`` is set.

    A dry run never touches ``writer``. An apply refuses before its first write
    when a repository lacks the ``shelved`` label, and records each action only
    after its write returned. A write that raises one of ``refused`` — any ``gh``
    failure: a 422, an expired token, a dropped network — is set aside as a
    :class:`Failure`, ledgered as ``failed``, and the run goes on; otherwise one
    item GitHub will not reopen would stall every later apply at the same place.
    A run that finishes records :func:`run_entry` last; it is not an entry.
    """
    if not apply:
        entries = tuple(_entry(a, MODE_DRY, now) for a in decided.actions)
        record((*entries, run_entry(MODE_DRY, now, len(entries))))
        return Outcome(entries)
    if writer is None:
        raise ValueError("an apply needs a writer")
    if decided.unlabelled:
        raise MissingLabelError(
            f"label {SHELVED!r} does not exist in {', '.join(decided.unlabelled)} — "
            "create it first; the sweep never creates labels"
        )
    entries: list[LedgerEntry] = []
    failures: list[Failure] = []
    for action in decided.actions:
        if action.verb in WRITE_VERBS:
            try:
                _perform(action, writer)
            except refused as exc:
                failures.append(Failure(action, str(exc)))
                record([_failed_entry(failures[-1], now)])
                continue
        entry = _entry(action, MODE_APPLIED, now)
        record([entry])
        entries.append(entry)
    record([run_entry(MODE_APPLIED, now, len(entries), len(failures))])
    return Outcome(tuple(entries), tuple(failures))


# --- rendering -------------------------------------------------------------


def said(entry: LedgerEntry) -> str:
    """The entry's verb as a reader should hear it: ``would …`` for a dry run."""
    return _SAID.get(entry.mode, {}).get(entry.action, entry.action)


def _line(entry: LedgerEntry) -> str:
    where = f"{entry.repo}#{entry.number}" if entry.number is not None else f"{entry.repo} {entry.ref}"
    idle = f", idle {entry.idle_days}d" if entry.idle_days is not None else ""
    return f"- {said(entry)} {where} — {entry.title} [{entry.rule}{idle}] {entry.reason}"


def render(entries: Sequence[LedgerEntry], *, apply: bool, unlabelled: Sequence[str]) -> str:
    """Counts per repository per rule, then one line per action."""
    mode = "APPLIED" if apply else "DRY RUN (nothing written to GitHub)"
    lines = [f"Abandoned-work sweep — {mode}: {len(entries)} actions"]
    counts = Counter((e.repo, e.rule) for e in entries)
    for (repo, rule), count in sorted(counts.items()):
        lines.append(f"  {repo}: {rule} {count}")
    if unlabelled:
        lines.append(
            f"WARNING: label {SHELVED!r} missing in {', '.join(unlabelled)} — --apply would refuse"
        )
    lines += [_line(e) for e in entries]
    return "\n".join(lines) + "\n"


__all__ = [
    "BRANCH_IDLE",
    "FINDING_IDLE",
    "INCUBATOR_IDLE",
    "MARKER",
    "PR_IDLE",
    "WORKTREE_IDLE",
    "Action",
    "Failure",
    "MissingLabelError",
    "Outcome",
    "Plan",
    "Survey",
    "SweepTarget",
    "Writer",
    "carried",
    "execute",
    "last_motion",
    "plan",
    "render",
    "run_entry",
    "said",
    "survey",
    "targets_from_registry",
    "wants_reopen",
]
