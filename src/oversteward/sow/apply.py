# ABOUTME: MIDDLE orchestration — turns a plan into one sync PR per context over injected runners.
# ABOUTME: Owns the never-push-to-the-registry-branch refusal, the G9 preflight, and the audit trail.

"""How a decided plan becomes one pull request per context.

Every step runs inside a **throwaway worktree cut from `origin/<branch>`** in
the target repo, never a branch checkout in the resident tree. That is a
deliberate departure from the pinned 2026-02 contract, which predates the
session-worktree discipline: `guard_main_worktree.py` now refuses the contract's
own `git checkout -b` step, and a checkout would disturb whatever the operator
has open. It also makes the contract's G1 clean-tree check structural — the
worktree is created clean and destroyed after the push.

Three invariants hold everywhere below:

- **One failed step aborts one context.** The rest of the run continues and the
  failure is carried into the report, because a batch that stops at the first
  problem hides every problem behind it.
- **No bypass, ever.** `--no-verify`, `--force`, `--admin` and `git add -A`
  appear nowhere; staging is by explicit path, and a pre-commit hook that
  objects is a finding, not an obstacle.
- **sow never merges.** It prints the `gh pr merge` line and stops. Several
  target repos disallow auto-merge, and every sync deserves a human read.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .plan import (
    ABORTED,
    DEPLOYED,
    EXIT_APPLY_FAILED,
    EXIT_COULD_NOT_LOOK,
    EXIT_MEASURED,
    NO_OP,
    SKIPPED,
    SYNC_BRANCH_PREFIX,
    UNREADABLE,
    UNREADABLE_CONTEXT,
    ContextOutcome,
    ContextPlan,
    SharedDeployResult,
    SowPlan,
    SowReport,
    exit_code,
    gate_consumer_format,
)
from .render import render_context_report
from .runners import CommandResult, GhCommand, GitCommand, MakeCommand, RuffCommand, SowError

CO_AUTHOR = "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"

#: Never mirrored to a Claude home: `inbox.md` is live per-machine state that a
#: deploy would overwrite, and `__pycache__` is build residue.
SKIPPED_FILES = frozenset({"inbox.md"})
SKIPPED_DIRS = frozenset({"__pycache__"})

__all__ = [
    "ABORTED",
    "DEPLOYED",
    "EXIT_APPLY_FAILED",
    "EXIT_COULD_NOT_LOOK",
    "EXIT_MEASURED",
    "NO_OP",
    "SKIPPED",
    "UNREADABLE_CONTEXT",
    "ContextOutcome",
    "Runners",
    "SharedDeployResult",
    "SowError",
    "SowReport",
    "apply_context",
    "apply_plan",
    "audit_entry",
    "deploy_shared",
    "exit_code",
    "push_sync_branch",
]

UNREADABLE_ACTION = UNREADABLE_CONTEXT


@dataclass(frozen=True)
class Runners:
    """Every external system apply talks to, injected as one bundle.

    Bundling is not cosmetic: it is what lets a gate test drive the whole
    orchestration with four stand-ins and no git, no gh and no network.
    """

    git: GitCommand
    gh: GhCommand
    ruff: RuffCommand
    verify: MakeCommand = field(default_factory=MakeCommand)


def push_sync_branch(
    git: GitCommand, repo_root: Path, sync_branch: str, registry_branch: str
) -> CommandResult:
    """Push, or refuse. The only place in sow that may push at all.

    A hard refusal rather than a convention: on GitHub Free a private repo
    cannot enforce branch protection, so this assertion is the whole protection
    the target's trunk has against a buggy sow.
    """
    if not sync_branch.startswith(SYNC_BRANCH_PREFIX):
        raise SowError(f"refusing to push '{sync_branch}' — not an {SYNC_BRANCH_PREFIX}* branch")
    if sync_branch == registry_branch:
        raise SowError(f"refusing to push the registry branch '{registry_branch}'")
    return git.run(repo_root, "push", "-u", "origin", sync_branch)


def _copy_members(canonical_shared: Path, worktree: Path, ctx: ContextPlan) -> tuple[str, ...]:
    """Byte-copy each deployable member into the worktree and prove the bytes match."""
    family = Path(canonical_shared) / "scripts" / "dev"
    for member in ctx.deployable:
        source = family / member.member
        destination = worktree / member.relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if destination.read_bytes() != source.read_bytes():
            raise SowError(f"copy of {member.relpath} does not match canonical bytes")
    return tuple(member.relpath for member in ctx.deployable)


def _consumer_format_gate(ruff: RuffCommand, repo_root: Path, worktree: Path, copied):
    python_paths = tuple(relpath for relpath in copied if relpath.endswith(".py"))
    available = ruff.available(repo_root)
    objections = (
        ruff.objections(repo_root, worktree, python_paths) if available and python_paths else ()
    )
    return gate_consumer_format(available, objections, python_paths)


def _commit(git: GitCommand, worktree: Path, ctx: ContextPlan, date: str, copied) -> CommandResult:
    staged = git.run(worktree, "add", "--", *copied)
    if not staged.ok:
        return staged
    subject = f"oversteward sync: {len(copied)} canonical family member(s) ({date})"
    body = f"{render_context_report(ctx, date)}\n{CO_AUTHOR}\n"
    return git.run(worktree, "commit", "-m", subject, "-m", body)


def _run_verify(verify_runner, repo_root: Path, worktree: Path, log_path: Path) -> CommandResult:
    """Borrow the target's environment, then run its own verify. Output to a file."""
    venv = repo_root / ".venv"
    link = worktree / ".venv"
    if venv.exists() and not link.exists():
        link.symlink_to(venv)
    return verify_runner.verify(worktree, log_path)


def _blocked_outcome(ctx: ContextPlan, blocking) -> ContextOutcome:
    action = UNREADABLE_ACTION if blocking.verdict == UNREADABLE else SKIPPED
    return ContextOutcome(ctx.context_id, action, (), f"{blocking.gate}: {blocking.detail}")


def _shas(ctx: ContextPlan) -> dict[str, dict[str, str | None]]:
    return {
        member.member: {"old": member.deployed_blob, "new": member.canonical_blob}
        for member in ctx.deployable
    }


def _deploy(
    ctx: ContextPlan,
    worktree: Path,
    *,
    canonical_shared: Path,
    runners: Runners,
    reports_dir: Path,
    date: str,
    verify: bool,
) -> ContextOutcome:
    repo_root = Path(ctx.repo_root or ".")
    names = tuple(member.member for member in ctx.deployable)
    copied = _copy_members(canonical_shared, worktree, ctx)
    gate = _consumer_format_gate(runners.ruff, repo_root, worktree, copied)
    if gate.blocking:
        return ContextOutcome(ctx.context_id, ABORTED, names, f"{gate.gate}: {gate.detail}")
    committed = _commit(runners.git, worktree, ctx, date, copied)
    if not committed.ok:
        return ContextOutcome(ctx.context_id, ABORTED, names, f"commit failed: {committed.text}")
    if verify:
        log_path = reports_dir / f"{date}-{ctx.context_id}-verify.log"
        verified = _run_verify(runners.verify, repo_root, worktree, log_path)
        if not verified.ok:
            detail = f"make verify failed — full output in {log_path}"
            return ContextOutcome(ctx.context_id, ABORTED, names, detail)
    pushed = push_sync_branch(runners.git, worktree, ctx.sync_branch, ctx.branch)
    if not pushed.ok:
        return ContextOutcome(ctx.context_id, ABORTED, names, f"push failed: {pushed.text}")
    body_path = reports_dir / f"{date}-{ctx.context_id}.md"
    body_path.write_text(render_context_report(ctx, date), encoding="utf-8")
    title = f"oversteward sync {date}: canonical shared/scripts/dev/ family"
    url = runners.gh.create_pr(worktree, ctx.branch, ctx.sync_branch, title, body_path)
    detail = f"{len(copied)} member(s) onto {ctx.sync_branch}"
    return ContextOutcome(ctx.context_id, DEPLOYED, names, detail, pr_url=url, shas=_shas(ctx))


def _open_worktree(
    git: GitCommand, repo_root: Path, ctx: ContextPlan
) -> tuple[Path, Path] | CommandResult:
    """A throwaway worktree cut from origin, or the failure that stopped it."""
    fetched = git.run(repo_root, "fetch", "origin", ctx.branch)
    if not fetched.ok:
        return fetched
    holder = Path(tempfile.mkdtemp(prefix="oversteward-sow-"))
    worktree = holder / ctx.context_id
    added = git.run(
        repo_root, "worktree", "add", "-B", ctx.sync_branch, str(worktree), f"origin/{ctx.branch}"
    )
    if not added.ok:
        shutil.rmtree(holder, ignore_errors=True)
        return added
    return holder, worktree


def apply_context(
    ctx: ContextPlan,
    *,
    canonical_shared: Path,
    runners: Runners,
    reports_dir: Path,
    date: str,
    verify: bool = False,
) -> ContextOutcome:
    """One context: gates, worktree, copy, commit, push, PR. Never touches its trunk."""
    blocking = ctx.blocking_gate
    if blocking is not None:
        return _blocked_outcome(ctx, blocking)
    if not ctx.deployable:
        return ContextOutcome(
            ctx.context_id, NO_OP, (), f"{len(ctx.members)} members identical or not adopted"
        )
    repo_root = Path(ctx.repo_root or ".")
    reports_dir.mkdir(parents=True, exist_ok=True)
    opened = _open_worktree(runners.git, repo_root, ctx)
    if isinstance(opened, CommandResult):
        return ContextOutcome(ctx.context_id, ABORTED, (), f"worktree setup failed: {opened.text}")
    holder, worktree = opened
    try:
        return _deploy(
            ctx,
            worktree,
            canonical_shared=canonical_shared,
            runners=runners,
            reports_dir=reports_dir,
            date=date,
            verify=verify,
        )
    except SowError as exc:
        return ContextOutcome(ctx.context_id, ABORTED, (), str(exc))
    finally:
        runners.git.run(repo_root, "worktree", "remove", str(worktree))
        runners.git.run(repo_root, "worktree", "prune")
        shutil.rmtree(holder, ignore_errors=True)


def audit_entry(outcome: ContextOutcome, now: datetime) -> dict:
    """One machine-readable line per context — what happened, and to which bytes."""
    return {
        "timestamp": now.isoformat(),
        "context_id": outcome.context_id,
        "action": outcome.action,
        "members": list(outcome.members),
        "shas": {name: dict(value) for name, value in (outcome.shas or {}).items()},
        "pr_url": outcome.pr_url,
        "reason": outcome.detail,
    }


def apply_plan(
    plan: SowPlan,
    *,
    canonical_shared: Path,
    runners: Runners,
    reports_dir: Path,
    now: datetime,
    verify: bool = False,
) -> SowReport:
    """Every context in the plan, in order. A dry run reaches no write path at all."""
    outcomes = tuple(
        apply_context(
            ctx,
            canonical_shared=canonical_shared,
            runners=runners,
            reports_dir=reports_dir,
            date=plan.date,
            verify=verify,
        )
        for ctx in plan.contexts
    )
    if plan.apply_requested:
        _write_audit(reports_dir, plan.date, outcomes, now)
    return SowReport(
        date=plan.date,
        applied=plan.apply_requested,
        outcomes=outcomes,
        members_checked=plan.members_checked,
        contexts_checked=len(plan.contexts),
        without_checkout=plan.without_checkout,
    )


def _write_audit(
    reports_dir: Path, date: str, outcomes: Sequence[ContextOutcome], now: datetime
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / f"{date}.jsonl").open("a", encoding="utf-8") as ledger:
        for outcome in outcomes:
            ledger.write(json.dumps(audit_entry(outcome, now)) + "\n")


def _is_skipped(source: Path, path: Path) -> bool:
    parts = path.relative_to(source).parts
    return path.name in SKIPPED_FILES or bool(set(parts) & SKIPPED_DIRS)


def _mirror(source: Path, target: Path) -> SharedDeployResult:
    copied = skipped = unchanged = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if _is_skipped(source, path):
            skipped += 1
            continue
        destination = target / path.relative_to(source)
        if destination.is_file() and destination.read_bytes() == path.read_bytes():
            unchanged += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        copied += 1
    return SharedDeployResult(str(target), copied, skipped, unchanged, True)


def deploy_shared(source: Path, targets: Sequence[Path]) -> tuple[SharedDeployResult, ...]:
    """Mirror canonical `shared/` into each Claude home. Additive — never a delete sweep.

    An absent home is reported unreachable rather than created: on this machine
    the Windows mirror lives behind `/mnt/c`, and a missing mount must read as
    "could not deploy there", never as a silently-created empty directory that
    every future run then reports as clean.
    """
    results = []
    for target in targets:
        destination = Path(target)
        if not destination.parent.is_dir():
            results.append(SharedDeployResult(str(destination), 0, 0, 0, False))
            continue
        results.append(_mirror(Path(source), destination))
    return tuple(results)
