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
from dataclasses import dataclass, field, replace
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
from .runners import (
    CommandResult,
    GhCommand,
    GitCommand,
    MakeCommand,
    RuffCommand,
    SowError,
    VenvBuilder,
)
from .venv import locked_venv_plan

CO_AUTHOR = "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"

#: Never mirrored to a Claude home: `inbox.md` is live per-machine state that a
#: deploy would overwrite, and `__pycache__` is build residue.
SKIPPED_FILES = frozenset({"inbox.md"})
SKIPPED_DIRS = frozenset({"__pycache__"})

NO_VERIFY_RULE_NOTE = "the target has no `make verify`; its pre-push hook is the full gate"

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
    venv: VenvBuilder = field(default_factory=VenvBuilder)


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


def _link_target_venv(repo_root: Path, worktree: Path) -> Path | None:
    """Lend the worktree the target's `.venv`, so its commit hooks and verify can run.

    Returns the link this call made, or None when the target has no venv or the
    worktree already holds one. Only a link made here is ever removed.
    """
    venv = repo_root / ".venv"
    link = worktree / ".venv"
    if not venv.exists() or link.exists() or link.is_symlink():
        return None
    link.symlink_to(venv)
    return link


def _provision_venv(
    repo_root: Path, worktree: Path, builder: VenvBuilder, log_path: Path, verify: bool
) -> tuple[Path | None, str]:
    """(link to remove, note for the report): the shared venv lent, or the worktree's own built.

    Only a verified uv target gets its own (see `venv`); it is a real directory
    inside the throwaway worktree, so the worktree's removal takes it. A `.venv`
    already in the worktree is refused rather than synced, because a link there
    would carry the sync into whatever environment it names.
    """
    plan = locked_venv_plan(worktree, repo_root / ".venv") if verify else None
    if plan is None:
        return _link_target_venv(repo_root, worktree), ""
    held = worktree / ".venv"
    if held.exists() or held.is_symlink():
        raise SowError("the worktree already holds a .venv; refusing to sync a venv into it")
    if not builder.build(worktree, plan.sync_args, plan.carried, log_path).ok:
        raise SowError(f"worktree venv build failed — full output in {log_path}")
    return None, plan.describe()


def _noted(outcome: ContextOutcome, note: str) -> ContextOutcome:
    return replace(outcome, detail=f"{outcome.detail}; {note}") if note else outcome


def _unlink_target_venv(link: Path | None) -> None:
    """Remove the borrowed link itself; never anything behind it."""
    if link is not None and link.is_symlink():
        link.unlink()


def _run_verify(verify_runner, worktree: Path, log_path: Path) -> tuple[bool, str]:
    """The target's own verify, output to a file: (may push, note for the report).

    A target with no `verify` rule may push, and the report says its pre-push
    hook is the full gate (the OS#800 ruling). sow does not check that the hook
    exists; the push runs whatever hook the target has. Only make's own
    "No rule" answer counts as absent, never the repo's name; any other failure
    aborts.
    """
    if verify_runner.verify(worktree, log_path).ok:
        return True, ""
    if not verify_runner.has_verify_rule(worktree):
        return True, NO_VERIFY_RULE_NOTE
    return False, f"make verify failed — full output in {log_path}"


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
    verify_note = ""
    if verify:
        log_path = reports_dir / f"{date}-{ctx.context_id}-verify.log"
        may_push, verify_note = _run_verify(runners.verify, worktree, log_path)
        if not may_push:
            return ContextOutcome(ctx.context_id, ABORTED, names, verify_note)
    pushed = push_sync_branch(runners.git, worktree, ctx.sync_branch, ctx.branch)
    if not pushed.ok:
        return ContextOutcome(ctx.context_id, ABORTED, names, f"push failed: {pushed.text}")
    body_path = reports_dir / f"{date}-{ctx.context_id}.md"
    body_path.write_text(render_context_report(ctx, date), encoding="utf-8")
    title = f"oversteward sync {date}: canonical shared/scripts/dev/ family"
    url = runners.gh.create_pr(worktree, ctx.branch, ctx.sync_branch, title, body_path)
    detail = f"{len(copied)} member(s) onto {ctx.sync_branch}"
    if verify_note:
        detail = f"{detail}; {verify_note}"
    return ContextOutcome(ctx.context_id, DEPLOYED, names, detail, pr_url=url, shas=_shas(ctx))


def _ref_sha(git: GitCommand, repo_root: Path, ref: str) -> str | None:
    """The commit a ref names, or None when it does not exist."""
    found = git.run(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return found.out.strip() if found.ok else None


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


def _close_worktree(git: GitCommand, repo_root: Path, holder: Path, worktree: Path) -> None:
    """Remove the worktree's directory and then git's registration of it.

    `git worktree remove` refuses a tree holding uncommitted or untracked files,
    which an abort before the commit or a verify's residue leaves. The directory
    is throwaway either way, so it is deleted, and only then can `prune` drop the
    registration: prune skips an entry whose directory still exists.
    """
    git.run(repo_root, "worktree", "remove", str(worktree))
    shutil.rmtree(holder, ignore_errors=True)
    git.run(repo_root, "worktree", "prune")


def _drop_unpushed_sync_branch(git: GitCommand, repo_root: Path, branch: str) -> None:
    """Delete the sync branch this run created, unless origin holds its tip.

    A pushed branch stays for `cleanup-merged` to delete after its PR merges. A
    tracking ref at any other commit, left by an earlier sync of the same name,
    does not count as pushed. The delete names the tip it read, and update-ref
    refuses it if the branch has moved since.
    """
    tip = _ref_sha(git, repo_root, f"refs/heads/{branch}")
    if tip is None or tip == _ref_sha(git, repo_root, f"refs/remotes/origin/{branch}"):
        return
    git.run(repo_root, "update-ref", "-d", f"refs/heads/{branch}", tip)


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
    branch_existed = _ref_sha(runners.git, repo_root, f"refs/heads/{ctx.sync_branch}") is not None
    opened = _open_worktree(runners.git, repo_root, ctx)
    if isinstance(opened, CommandResult):
        return ContextOutcome(ctx.context_id, ABORTED, (), f"worktree setup failed: {opened.text}")
    holder, worktree = opened
    venv_link = None
    try:
        build_log = reports_dir / f"{date}-{ctx.context_id}-venv.log"
        venv_link, venv_note = _provision_venv(
            repo_root, worktree, runners.venv, build_log, verify
        )
        outcome = _deploy(
            ctx,
            worktree,
            canonical_shared=canonical_shared,
            runners=runners,
            reports_dir=reports_dir,
            date=date,
            verify=verify,
        )
        return _noted(outcome, venv_note)
    except SowError as exc:
        return ContextOutcome(ctx.context_id, ABORTED, (), str(exc))
    finally:
        _unlink_target_venv(venv_link)
        _close_worktree(runners.git, repo_root, holder, worktree)
        if not branch_existed:
            _drop_unpushed_sync_branch(runners.git, repo_root, ctx.sync_branch)


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
