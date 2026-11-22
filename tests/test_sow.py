# ABOUTME: Tests for the sow writer — member classification, every safety gate, and an end-to-end apply.
# ABOUTME: Gate tests inject fakes and touch neither git nor the network; the apply test uses real git repos.

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oversteward.sow.apply import (
    ABORTED,
    DEPLOYED,
    EXIT_APPLY_FAILED,
    EXIT_COULD_NOT_LOOK,
    EXIT_MEASURED,
    NO_OP,
    SKIPPED,
    UNREADABLE,
    Runners,
    SowReport,
    apply_plan,
    deploy_shared,
    exit_code,
    push_sync_branch,
)
from oversteward.sow.canon import CanonHistory, canonical_blobs, observe_registry
from oversteward.sow.plan import (
    BLOCKED,
    DEPLOYABLE_STATUSES,
    DIVERGED,
    IDENTICAL,
    MISSING,
    NOT_ADOPTED,
    NOT_APPLICABLE,
    PASS,
    STALE,
    SYNC_BRANCH_PREFIX,
    UNREADABLE as GATE_UNREADABLE,
    ContextObservation,
    ContextPlan,
    MemberPlan,
    classify_member_status,
    gate_consumer_format,
    gate_context_registered,
    gate_explicit_apply,
    gate_lock,
    gate_no_stacked_pr,
    gate_not_skip_sow,
    plan,
    sync_branch_for,
)
from oversteward.sow.render import render_plan
from oversteward.sow.runners import (
    CommandResult,
    GitCommand,
    MakeCommand,
    SowError,
    SowLock,
    VenvBuilder,
    names_no_verify_rule,
)

TODAY = "2026-08-28"
NOW = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)

CANON_V1 = "#!/usr/bin/env bash\necho v1\n"
CANON_V2 = "#!/usr/bin/env bash\necho v2\n"
DOCTOR = "# ABOUTME: doctor\nprint('doctor')\n"
WITH_ENV = "# ABOUTME: env runner\nprint('env')\n"

MEMBER = "new-session.sh"
DOCTOR_MEMBER = "worktree_doctor.py"
ENV_MEMBER = "with_test_env.py"


# --------------------------------------------------------------------------
# fakes


class FakeGit:
    """Emulates only the verbs sow uses; `worktree add` really makes the directory."""

    def __init__(self, fail_on: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail_on = fail_on

    def run(self, cwd: Path, *args: str) -> CommandResult:
        self.calls.append((str(cwd), args))
        if args and args[0] in self.fail_on:
            return CommandResult(False, "", f"fake git refused {args[0]}")
        if args[:2] == ("worktree", "add"):
            Path(args[-2]).mkdir(parents=True, exist_ok=True)
        return CommandResult(True, "", "")


class FakeGh:
    def __init__(self, url: str = "https://github.com/NathanKrupa/pickup/pull/7") -> None:
        self.url = url
        self.created: list[tuple[str, str, str]] = []

    def open_sync_branches(self, cwd: Path, prefix: str) -> tuple[str, ...] | None:
        return ()

    def create_pr(self, cwd: Path, base: str, head: str, title: str, body_path: Path) -> str:
        self.created.append((base, head, body_path.read_text(encoding="utf-8")))
        return self.url


class FakeVerify:
    def __init__(self, ok: bool = True, has_rule: bool = True) -> None:
        self.ok = ok
        self.has_rule = has_rule
        self.logs: list[str] = []

    def verify(self, worktree: Path, log_path: Path) -> CommandResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake verify output\n", encoding="utf-8")
        self.logs.append(str(log_path))
        return CommandResult(self.ok, "fake verify output", "" if self.ok else "verify failed")

    def has_verify_rule(self, worktree: Path) -> bool:
        return self.has_rule


class FakeRuff:
    def __init__(self, objections: tuple[str, ...] = (), available: bool = True) -> None:
        self._objections = objections
        self._available = available
        self.asked: list[tuple[str, ...]] = []

    def available(self, repo_root: Path) -> bool:
        return self._available

    def objections(
        self, repo_root: Path, worktree: Path, relpaths: tuple[str, ...]
    ) -> tuple[str, ...]:
        self.asked.append(relpaths)
        return self._objections


# --------------------------------------------------------------------------
# git fixtures


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a git hook's inherited ``GIT_*`` variables away from the scratch repos.

    A hook exports its location variables to the suite it runs, and each one
    re-points git away from the ``-C`` tree onto the hook's own repository (OS#807).
    """
    for name in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(name)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def canon(tmp_path: Path) -> Path:
    """A canon repo whose new-session.sh has two committed generations."""
    root = tmp_path / "canon"
    _init(root)
    _write(root, "shared/scripts/dev/new-session.sh", CANON_V1)
    _write(root, "shared/scripts/dev/worktree_doctor.py", DOCTOR)
    _write(root, "shared/scripts/dev/with_test_env.py", WITH_ENV)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "canon v1")
    _write(root, "shared/scripts/dev/new-session.sh", CANON_V2)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "canon v2")
    return root


@pytest.fixture
def pickup(tmp_path: Path) -> Path:
    """A pickup repo with a real bare origin: stale member, diverged member, missing member."""
    origin = tmp_path / "pickup.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, capture_output=True
    )
    root = tmp_path / "pickup"
    _init(root)
    _git(root, "remote", "add", "origin", str(origin))
    _write(root, "scripts/dev/new-session.sh", CANON_V1)
    _write(root, "scripts/dev/worktree_doctor.py", "# ABOUTME: local hack\nprint('hacked')\n")
    _write(root, "CLAUDE.md", "Run scripts/dev/with_test_env.py before every verify.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "pickup init")
    _git(root, "push", "-q", "-u", "origin", "main")
    return root


def _members(canon_root: Path) -> list[str]:
    return sorted(p.name for p in (canon_root / "shared/scripts/dev").iterdir())


def _observe(pickup_root: Path) -> ContextObservation:
    registry = {
        "contexts": [
            {
                "id": "pickup",
                "branch": "main",
                "local_path": str(pickup_root),
                "claude_md_path": "CLAUDE.md",
            }
        ]
    }
    observations, without = observe_registry(
        registry, _members(pickup_root.parent / "canon"), GitCommand(), FakeGh(), fetch=True
    )
    assert without == []
    return observations[0]


# --------------------------------------------------------------------------
# classification


def test_a_copy_matching_canonical_is_identical():
    assert classify_member_status("aaa", "aaa", {"aaa", "bbb"}, True) == IDENTICAL


def test_a_copy_matching_an_older_canon_blob_is_stale():
    assert classify_member_status("aaa", "bbb", {"aaa", "bbb"}, True) == STALE


def test_a_copy_matching_no_canon_blob_is_diverged():
    assert classify_member_status("aaa", "zzz", {"aaa", "bbb"}, True) == DIVERGED


def test_an_absent_member_the_doctrine_names_is_missing():
    assert classify_member_status("aaa", None, {"aaa"}, True) == MISSING


def test_an_absent_member_nothing_references_is_not_adopted():
    assert classify_member_status("aaa", None, {"aaa"}, False) == NOT_ADOPTED


def test_only_stale_and_missing_are_deployable():
    every = (IDENTICAL, STALE, DIVERGED, MISSING, NOT_ADOPTED)
    ctx = ContextPlan(
        context_id="pickup",
        branch="main",
        sync_branch=sync_branch_for(TODAY),
        repo_root="/tmp/pickup",
        gates=(),
        members=tuple(
            MemberPlan(status, f"scripts/dev/{status}", status, "aaa", None) for status in every
        ),
    )
    assert {m.status for m in ctx.deployable} == {STALE, MISSING}
    assert {m.status for m in ctx.diverged} == {DIVERGED}
    assert DEPLOYABLE_STATUSES == frozenset({STALE, MISSING})


def test_canon_history_carries_every_generation_of_a_member(canon: Path):
    history = CanonHistory(canon, GitCommand())
    blobs = history.blobs(MEMBER)
    assert len(blobs) == 2
    assert history.current_blob(MEMBER) in blobs


def test_a_repo_copy_of_the_previous_generation_reads_as_stale(canon: Path, pickup: Path):
    history = CanonHistory(canon, GitCommand())
    canonical = canonical_blobs(canon, canon / "shared", GitCommand())
    observed = _observe(pickup)
    assert observed.readable
    status = classify_member_status(
        canonical[MEMBER], observed.deployed[MEMBER], history.blobs(MEMBER), True
    )
    assert status == STALE


def test_a_member_deployed_as_an_in_tree_symlink_reads_as_identical(canon: Path):
    """OverSteward links its own deployed copies into shared/ (OS#576)."""
    link = canon / "scripts/dev" / MEMBER
    link.parent.mkdir(parents=True)
    link.symlink_to(f"../../shared/scripts/dev/{MEMBER}")
    _git(canon, "add", "-A")
    _git(canon, "commit", "-qm", "link the deployed copy")
    _git(canon, "update-ref", "refs/remotes/origin/main", "HEAD")
    registry = {
        "contexts": [
            {"id": "self", "branch": "main", "local_path": str(canon), "claude_md_path": "CLAUDE.md"}
        ]
    }
    (observed,), _ = observe_registry(
        registry, _members(canon), GitCommand(), FakeGh(), fetch=False
    )
    canonical = canonical_blobs(canon, canon / "shared", GitCommand())
    history = CanonHistory(canon, GitCommand())
    status = classify_member_status(
        canonical[MEMBER], observed.deployed[MEMBER], history.blobs(MEMBER), True
    )
    assert status == IDENTICAL


def test_a_dangling_link_in_a_consumer_reads_as_diverged_not_missing(canon: Path, pickup: Path):
    """A leaked OverSteward link must never read as missing — sow would deploy through it."""
    link = pickup / "scripts/dev" / ENV_MEMBER
    link.symlink_to(f"../../shared/scripts/dev/{ENV_MEMBER}")
    _git(pickup, "add", "-A")
    _git(pickup, "commit", "-qm", "a leaked link")
    _git(pickup, "push", "-q", "origin", "main")
    observed = _observe(pickup)
    canonical = canonical_blobs(canon, canon / "shared", GitCommand())
    history = CanonHistory(canon, GitCommand())
    status = classify_member_status(
        canonical[ENV_MEMBER], observed.deployed[ENV_MEMBER], history.blobs(ENV_MEMBER), True
    )
    assert status == DIVERGED


# --------------------------------------------------------------------------
# gates


def test_g2_passes_when_no_sync_branch_is_open():
    assert gate_no_stacked_pr(()).verdict == PASS


def test_g2_blocks_when_a_sync_branch_is_open():
    verdict = gate_no_stacked_pr(("oversteward/sync-2026-08-01",))
    assert verdict.verdict == BLOCKED
    assert "oversteward/sync-2026-08-01" in verdict.detail


def test_g2_is_unreadable_when_the_pr_list_cannot_be_read():
    assert gate_no_stacked_pr(None).verdict == GATE_UNREADABLE


def test_g3_passes_for_a_registered_context():
    assert gate_context_registered("pickup", ["pickup", "other"]).verdict == PASS


def test_g3_is_unreadable_for_an_unknown_context_id():
    verdict = gate_context_registered("ghost", ["pickup"])
    assert verdict.verdict == GATE_UNREADABLE
    assert "ghost" in verdict.detail


def test_g4_passes_when_skip_sow_is_absent():
    assert gate_not_skip_sow(False).verdict == PASS


def test_g4_blocks_a_skip_sow_context():
    verdict = gate_not_skip_sow(True)
    assert verdict.verdict == BLOCKED
    assert "skip_sow" in verdict.detail


def test_g7_passes_when_the_lock_is_free(tmp_path: Path):
    with SowLock(tmp_path / ".sow.lock") as lock:
        assert lock.acquired
        assert gate_lock(lock.acquired, str(tmp_path / ".sow.lock")).verdict == PASS


def test_g7_blocks_a_second_concurrent_holder(tmp_path: Path):
    path = tmp_path / ".sow.lock"
    with SowLock(path) as first:
        assert first.acquired
        second = SowLock(path)
        assert second.acquire() is False
        assert gate_lock(second.acquired, str(path)).verdict == GATE_UNREADABLE
    assert not path.exists()


def test_g8_blocks_writes_without_apply():
    verdict = gate_explicit_apply(False)
    assert verdict.verdict == BLOCKED
    assert "--apply" in verdict.detail


def test_g8_passes_with_apply():
    assert gate_explicit_apply(True).verdict == PASS


def test_g9_passes_when_the_target_ruff_raises_no_objection():
    assert gate_consumer_format(True, (), ("scripts/dev/new-session.sh",)).verdict == PASS


def test_g9_blocks_and_names_the_exclusion_the_repo_needs():
    verdict = gate_consumer_format(True, ("would reformat: scripts/dev/x.py",), ("scripts/dev/x.py",))
    assert verdict.verdict == BLOCKED
    assert "extend-exclude" in verdict.detail
    assert "force-exclude = true" in verdict.detail
    assert "scripts/dev/" in verdict.detail


def test_g9_is_not_applicable_when_the_repo_has_no_ruff():
    verdict = gate_consumer_format(False, (), ("scripts/dev/x.py",))
    assert verdict.verdict == NOT_APPLICABLE
    assert verdict.verdict != PASS


def test_push_refuses_a_branch_that_is_not_a_sync_branch():
    git = FakeGit()
    with pytest.raises(SowError):
        push_sync_branch(git, Path("/tmp/repo"), "feature/x", "main")
    assert git.calls == []


def test_push_refuses_the_registry_branch():
    git = FakeGit()
    with pytest.raises(SowError):
        push_sync_branch(git, Path("/tmp/repo"), "main", "main")
    assert git.calls == []


def test_push_accepts_the_sync_branch():
    git = FakeGit()
    result = push_sync_branch(git, Path("/tmp/repo"), sync_branch_for(TODAY), "main")
    assert result.ok
    assert git.calls[0][1] == ("push", "-u", "origin", f"{SYNC_BRANCH_PREFIX}{TODAY}")


# --------------------------------------------------------------------------
# plan


def _plan(observation: ContextObservation, canon_root: Path, *, apply_requested: bool = True):
    history = CanonHistory(canon_root, GitCommand())
    members = _members(canon_root)
    canonical = canonical_blobs(canon_root, canon_root / "shared", GitCommand())
    return plan(
        [observation],
        canonical,
        history.history(members),
        date=TODAY,
        apply_requested=apply_requested,
        registered_ids=[observation.context_id],
    )


def test_a_plan_classifies_stale_diverged_and_missing_in_one_pass(canon: Path, pickup: Path):
    result = _plan(_observe(pickup), canon)
    statuses = {m.member: m.status for m in result.contexts[0].members}
    assert statuses[MEMBER] == STALE
    assert statuses[DOCTOR_MEMBER] == DIVERGED
    assert statuses[ENV_MEMBER] == MISSING
    assert {m.member for m in result.contexts[0].deployable} == {MEMBER, ENV_MEMBER}


def test_a_skip_sow_context_is_reported_and_never_deployed(canon: Path, pickup: Path):
    observed = _observe(pickup)
    skipped = ContextObservation(
        context_id=observed.context_id,
        branch=observed.branch,
        repo_root=observed.repo_root,
        skip_sow=True,
        readable=observed.readable,
        doctrine_text=observed.doctrine_text,
        deployed=observed.deployed,
        open_sync_branches=(),
    )
    result = _plan(skipped, canon)
    ctx = result.contexts[0]
    assert ctx.blocking_gate is not None
    assert ctx.blocking_gate.gate == "G4"


def test_an_unreadable_origin_is_a_could_not_look_context(canon: Path):
    unreadable = ContextObservation(
        context_id="dark",
        branch="main",
        repo_root="/nonexistent",
        skip_sow=False,
        readable=False,
    )
    result = _plan(unreadable, canon)
    assert result.contexts[0].blocking_gate.verdict == GATE_UNREADABLE


def test_a_plan_with_nothing_to_do_names_the_count_it_checked(canon: Path, pickup: Path):
    observed = _observe(pickup)
    identical = ContextObservation(
        context_id=observed.context_id,
        branch=observed.branch,
        repo_root=observed.repo_root,
        skip_sow=False,
        readable=True,
        doctrine_text=observed.doctrine_text,
        deployed=canonical_blobs(canon, canon / "shared", GitCommand()),
        open_sync_branches=(),
    )
    result = _plan(identical, canon)
    text = render_plan(result)
    assert result.contexts[0].deployable == ()
    assert "3" in text
    assert "nothing to do" in text.lower()


# --------------------------------------------------------------------------
# apply


def _apply(canon_root: Path, pickup_root: Path, tmp_path: Path, **kwargs):
    gh = kwargs.pop("gh", None) or FakeGh()
    ruff = kwargs.pop("ruff", None) or FakeRuff()
    git = kwargs.pop("git", None) or GitCommand()
    verify_runner = kwargs.pop("verify_runner", None) or FakeVerify()
    venv_builder = kwargs.pop("venv_builder", None) or VenvBuilder()
    apply_requested = kwargs.pop("apply_requested", True)
    observation = kwargs.pop("observation", None) or _observe(pickup_root)
    reports = tmp_path / "reports" / "sow"
    result = _plan(observation, canon_root, apply_requested=apply_requested)
    report = apply_plan(
        result,
        canonical_shared=canon_root / "shared",
        runners=Runners(git=git, gh=gh, ruff=ruff, verify=verify_runner, venv=venv_builder),
        reports_dir=reports,
        now=NOW,
        **kwargs,
    )
    return report, gh, ruff, reports


def test_apply_deploys_stale_and_missing_members_and_opens_one_pr(
    canon: Path, pickup: Path, tmp_path: Path
):
    report, gh, _ruff, _reports = _apply(canon, pickup, tmp_path)
    outcome = report.outcomes[0]
    assert outcome.action == DEPLOYED
    assert set(outcome.members) == {MEMBER, ENV_MEMBER}
    assert outcome.pr_url == gh.url
    assert len(gh.created) == 1
    base, head, _body = gh.created[0]
    assert base == "main"
    assert head == sync_branch_for(TODAY)


def test_apply_pushes_byte_identical_copies_to_the_sync_branch(
    canon: Path, pickup: Path, tmp_path: Path
):
    _apply(canon, pickup, tmp_path)
    ref = f"origin/{sync_branch_for(TODAY)}"
    assert _git(pickup, "show", f"{ref}:scripts/dev/{MEMBER}") == CANON_V2.strip()
    assert _git(pickup, "show", f"{ref}:scripts/dev/{ENV_MEMBER}") == WITH_ENV.strip()


def test_apply_never_touches_the_fixture_default_branch(canon: Path, pickup: Path, tmp_path: Path):
    before = _git(pickup, "rev-parse", "origin/main")
    _apply(canon, pickup, tmp_path)
    assert _git(pickup, "rev-parse", "origin/main") == before
    assert _git(pickup, "show", f"origin/main:scripts/dev/{MEMBER}") == CANON_V1.strip()


def test_apply_leaves_a_diverged_member_untouched(canon: Path, pickup: Path, tmp_path: Path):
    _apply(canon, pickup, tmp_path)
    ref = f"origin/{sync_branch_for(TODAY)}"
    assert "hacked" in _git(pickup, "show", f"{ref}:scripts/dev/{DOCTOR_MEMBER}")


def test_apply_writes_one_audit_line_per_context(canon: Path, pickup: Path, tmp_path: Path):
    report, gh, _ruff, reports = _apply(canon, pickup, tmp_path)
    lines = (reports / f"{TODAY}.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["context_id"] == "pickup"
    assert entry["action"] == DEPLOYED
    assert entry["pr_url"] == gh.url
    assert sorted(entry["members"]) == sorted([ENV_MEMBER, MEMBER])
    assert entry["shas"][MEMBER]["new"] != entry["shas"][MEMBER]["old"]
    assert entry["timestamp"].startswith("2026-08-28T09:00")
    assert report.date == TODAY


def test_a_dry_run_writes_nothing(canon: Path, pickup: Path, tmp_path: Path):
    before = _git(pickup, "rev-parse", "origin/main")
    report, gh, _ruff, reports = _apply(canon, pickup, tmp_path, apply_requested=False)
    assert report.outcomes[0].action == SKIPPED
    assert gh.created == []
    assert _git(pickup, "rev-parse", "origin/main") == before
    assert not (reports / f"{TODAY}.jsonl").exists()
    assert "oversteward/sync" not in _git(pickup, "branch", "--list", "--all")


def test_a_g9_objection_aborts_the_context_without_opening_a_pr(
    canon: Path, pickup: Path, tmp_path: Path
):
    ruff = FakeRuff(objections=("would reformat: scripts/dev/with_test_env.py",))
    report, gh, _ruff, _reports = _apply(canon, pickup, tmp_path, ruff=ruff)
    assert report.outcomes[0].action == ABORTED
    assert "extend-exclude" in report.outcomes[0].detail
    assert gh.created == []
    assert "oversteward/sync" not in _git(pickup, "branch", "--list", "--remote")


def test_g9_only_asks_about_python_files(canon: Path, pickup: Path, tmp_path: Path):
    ruff = FakeRuff()
    _apply(canon, pickup, tmp_path, ruff=ruff)
    assert ruff.asked == [(f"scripts/dev/{ENV_MEMBER}",)]


def test_a_failed_verify_aborts_the_context_and_keeps_the_log(
    canon: Path, pickup: Path, tmp_path: Path
):
    report, gh, _ruff, reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=FakeVerify(ok=False)
    )
    assert report.outcomes[0].action == ABORTED
    assert "verify" in report.outcomes[0].detail
    assert gh.created == []
    assert list(reports.glob("*verify*"))


# --------------------------------------------------------------------------
# the target's own environment and gates


def _hooked_venv(pickup_root: Path, tmp_path: Path) -> Path:
    """Give the pickup a `.venv` tool and a pre-commit hook that refuses without it.

    The hook runs at the commit's worktree root, as a target's hook does, and
    records where it ran and what its `.venv` pointed at into `hook-seen`.
    """
    seen = tmp_path / "hook-seen"
    tool = pickup_root / ".venv" / "bin" / "gatetool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    hook = pickup_root / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n%s\\n" "$(pwd)" "$(readlink .venv)" > "{seen}"\n'
        '[ -x .venv/bin/gatetool ] || { echo "no gate runner found" >&2; exit 1; }\n'
        "exec .venv/bin/gatetool\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return seen


def _tree_state(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_a_commit_hook_that_needs_the_target_venv_commits_under_sow(
    canon: Path, pickup: Path, tmp_path: Path
):
    _hooked_venv(pickup, tmp_path)
    report, gh, _ruff, _reports = _apply(canon, pickup, tmp_path)
    outcome = report.outcomes[0]
    assert outcome.action == DEPLOYED, outcome.detail
    assert "no gate runner found" not in outcome.detail
    assert len(gh.created) == 1


def test_the_commit_hook_sees_the_target_venv_through_the_worktree_link(
    canon: Path, pickup: Path, tmp_path: Path
):
    seen = _hooked_venv(pickup, tmp_path)
    _apply(canon, pickup, tmp_path, verify=True)
    ran_in, link_target = seen.read_text(encoding="utf-8").splitlines()
    assert Path(ran_in) != pickup
    assert Path(link_target) == pickup / ".venv"


def test_the_worktree_link_is_gone_and_the_target_venv_untouched_after_the_run(
    canon: Path, pickup: Path, tmp_path: Path
):
    seen = _hooked_venv(pickup, tmp_path)
    before = _tree_state(pickup / ".venv")
    _apply(canon, pickup, tmp_path, verify=True)
    ran_in = Path(seen.read_text(encoding="utf-8").splitlines()[0])
    assert not (ran_in / ".venv").is_symlink()
    assert not (ran_in / ".venv").exists()
    assert _tree_state(pickup / ".venv") == before
    assert (pickup / ".venv").is_dir() and not (pickup / ".venv").is_symlink()


class RecordingGit(GitCommand):
    """Real git that keeps the result of every `worktree remove`."""

    def __init__(self) -> None:
        self.removals: list[CommandResult] = []

    def run(self, cwd: Path, *args: str) -> CommandResult:
        result = super().run(cwd, *args)
        if args[:2] == ("worktree", "remove"):
            self.removals.append(result)
        return result


def test_git_removes_the_worktree_itself_because_the_link_is_gone_first(
    canon: Path, pickup: Path, tmp_path: Path
):
    # The pickup ignores nothing, so a link left behind is an untracked file and
    # a plain `git worktree remove` refuses it; only the temp-dir sweep would hide that.
    _hooked_venv(pickup, tmp_path)
    git = RecordingGit()
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path, git=git, verify=True)
    assert report.outcomes[0].action == DEPLOYED
    assert len(git.removals) == 1
    assert git.removals[0].ok, git.removals[0].text


def test_a_worktree_that_already_holds_a_venv_is_neither_linked_nor_stripped(
    canon: Path, pickup: Path, tmp_path: Path
):
    _write(pickup, ".venv/tracked.txt", "committed by the target\n")
    _git(pickup, "add", "-f", ".venv/tracked.txt")
    _git(pickup, "commit", "-qm", "tracked venv file")
    _git(pickup, "push", "-q", "origin", "main")
    git = RecordingGit()
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path, git=git, verify=True)
    assert report.outcomes[0].action == DEPLOYED, report.outcomes[0].detail
    ref = f"origin/{sync_branch_for(TODAY)}"
    assert _git(pickup, "show", f"{ref}:.venv/tracked.txt") == "committed by the target"
    assert git.removals and git.removals[0].ok, git.removals[0].text


def test_a_target_with_no_verify_rule_is_pushed_and_says_its_push_hook_gates(
    canon: Path, pickup: Path, tmp_path: Path
):
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    outcome = report.outcomes[0]
    assert outcome.action == DEPLOYED, outcome.detail
    assert "has no `make verify`" in outcome.detail
    assert "pre-push hook is the full gate" in outcome.detail
    assert len(gh.created) == 1
    assert sync_branch_for(TODAY) in _git(pickup, "branch", "--list", "--remote")


def _commit_makefile(pickup_root: Path, text: str) -> None:
    _write(pickup_root, "Makefile", text)
    _git(pickup_root, "add", "Makefile")
    _git(pickup_root, "commit", "-qm", "makefile")
    _git(pickup_root, "push", "-q", "origin", "main")


def test_a_failing_verify_rule_still_aborts(canon: Path, pickup: Path, tmp_path: Path):
    _commit_makefile(pickup, "verify:\n\tfalse\n")
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == ABORTED
    assert "make verify failed" in report.outcomes[0].detail
    assert gh.created == []
    assert "oversteward/sync" not in _git(pickup, "branch", "--list", "--remote")


def test_a_verify_rule_missing_a_prerequisite_aborts_rather_than_reading_as_absent(
    canon: Path, pickup: Path, tmp_path: Path
):
    _commit_makefile(pickup, "verify: lint\n\ttrue\n")
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == ABORTED
    assert "make verify failed" in report.outcomes[0].detail
    assert gh.created == []


def test_a_verify_rule_whose_sub_make_has_no_verify_aborts(
    canon: Path, pickup: Path, tmp_path: Path
):
    _write(pickup, "sub/Makefile", "all:\n\ttrue\n")
    _git(pickup, "add", "sub/Makefile")
    _commit_makefile(pickup, "verify:\n\t$(MAKE) -C sub verify\n")
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == ABORTED, report.outcomes[0].detail
    assert "make verify failed" in report.outcomes[0].detail
    assert gh.created == []


def test_a_passing_verify_is_never_dry_run(canon: Path, pickup: Path, tmp_path: Path):
    # `+` lines execute even under `make -n`; this one touches its marker only then.
    probed = tmp_path / "probed"
    dry_run = "$(findstring n,$(firstword -$(MAKEFLAGS)))"
    _commit_makefile(
        pickup, f'verify:\n\t+@if [ -n "{dry_run}" ]; then touch "{probed}"; fi\n'
    )
    report, _gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == DEPLOYED
    assert not probed.exists()
    assert MakeCommand().has_verify_rule(pickup) is True
    assert probed.exists()


def test_a_passing_verify_rule_pushes_without_the_no_verify_note(
    canon: Path, pickup: Path, tmp_path: Path
):
    _commit_makefile(pickup, "verify:\n\ttrue\n")
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == DEPLOYED
    assert "make verify" not in report.outcomes[0].detail
    assert len(gh.created) == 1


def test_a_failed_verify_with_a_rule_present_never_reads_as_absent(
    canon: Path, pickup: Path, tmp_path: Path
):
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=FakeVerify(ok=False, has_rule=True)
    )
    assert report.outcomes[0].action == ABORTED
    assert gh.created == []


@pytest.mark.parametrize(
    ("text", "absent"),
    [
        ("make: *** No rule to make target 'verify'.  Stop.", True),
        ("make: *** No rule to make target `verify'.  Stop.", True),
        ("make: *** No rule to make target 'lint', needed by 'verify'.  Stop.", False),
        ("make: *** No rule to make target 'verify', needed by 'all'.  Stop.", False),
        ("make: *** No rule to make target 'verify-fast'.  Stop.", False),
        (
            "make[1]: *** No rule to make target 'verify'.  Stop.\n"
            "make: *** [Makefile:2: verify] Error 2",
            False,
        ),
        ("make[1]: *** No rule to make target 'verify'.  Stop.", False),
        ("tool said: make: *** No rule to make target 'verify'.  Stop.", False),
        ("/usr/bin/make: *** No rule to make target 'verify'.  Stop.", True),
        ("make: Entering directory '/x'\nmake: *** No rule to make target 'verify'.  Stop.", True),
        ("Makefile:3: *** missing separator.  Stop.", False),
        ("", False),
    ],
)
def test_only_makes_own_no_rule_for_verify_reads_as_absent(text: str, absent: bool):
    assert names_no_verify_rule(text) is absent


def test_make_reports_no_verify_rule_only_where_there_is_none(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.mkdir()
    other = tmp_path / "other"
    _write(other, "Makefile", "all:\n\ttrue\n")
    present = tmp_path / "present"
    _write(present, "Makefile", "verify:\n\ttouch ran\n")
    echoing = tmp_path / "echoing"
    # A `+` line runs even under -n, so a passing dry run prints make's exact words.
    _write(
        echoing,
        "Makefile",
        "verify:\n\t+@echo \"make: *** No rule to make target 'verify'.  Stop.\"\n",
    )
    make = MakeCommand()
    assert make.has_verify_rule(bare) is False
    assert make.has_verify_rule(other) is False
    assert make.has_verify_rule(present) is True
    assert make.has_verify_rule(echoing) is True
    assert not (present / "ran").exists()


def test_a_failed_push_aborts_the_context(canon: Path, pickup: Path, tmp_path: Path):
    report, gh, _ruff, _reports = _apply(canon, pickup, tmp_path, git=FakeGit(fail_on=("push",)))
    assert report.outcomes[0].action == ABORTED
    assert gh.created == []


def test_apply_never_passes_a_hook_bypass_flag(canon: Path, pickup: Path, tmp_path: Path):
    git = FakeGit()
    _apply(canon, pickup, tmp_path, git=git)
    flat = [arg for _cwd, args in git.calls for arg in args]
    assert "--no-verify" not in flat
    assert "-n" not in flat
    assert "--force" not in flat
    assert "-A" not in flat


# --------------------------------------------------------------------------
# what a run leaves behind in the target (OS#803)


def _registered_worktrees(root: Path) -> list[Path]:
    listing = _git(root, "worktree", "list", "--porcelain").splitlines()
    return [Path(line.split(" ", 1)[1]) for line in listing if line.startswith("worktree ")]


def _local_sync_branches(root: Path) -> list[str]:
    pattern = f"{SYNC_BRANCH_PREFIX}*"
    return _git(root, "branch", "--list", pattern, "--format=%(refname:short)").split()


def _pre_push_refusing(pickup_root: Path) -> None:
    hook = pickup_root / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho 'push refused by the target' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


class FailingGh(FakeGh):
    """A gh whose `pr create` fails after the push has already landed."""

    def create_pr(self, cwd: Path, base: str, head: str, title: str, body_path: Path) -> str:
        raise SowError("gh pr create failed: fake refusal")


def test_a_deploy_whose_verify_leaves_an_untracked_file_registers_no_worktree(
    canon: Path, pickup: Path, tmp_path: Path
):
    # `git worktree remove` refuses a tree holding an untracked file, which any
    # `make verify` that writes into its tree leaves behind.
    _commit_makefile(pickup, "verify:\n\ttouch verify-residue\n")
    report, gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=MakeCommand()
    )
    assert report.outcomes[0].action == DEPLOYED, report.outcomes[0].detail
    assert len(gh.created) == 1
    assert _registered_worktrees(pickup) == [pickup]


def test_a_deploy_on_a_clean_tree_registers_no_worktree(canon: Path, pickup: Path, tmp_path: Path):
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path)
    assert report.outcomes[0].action == DEPLOYED, report.outcomes[0].detail
    assert _registered_worktrees(pickup) == [pickup]


def test_an_abort_before_the_commit_registers_no_worktree(
    canon: Path, pickup: Path, tmp_path: Path
):
    # G9 refuses after the copy and before the commit, so the tree is dirty.
    ruff = FakeRuff(objections=("would reformat: scripts/dev/with_test_env.py",))
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path, ruff=ruff)
    assert report.outcomes[0].action == ABORTED
    assert _registered_worktrees(pickup) == [pickup]


def _abort_before_commit(pickup_root: Path) -> dict:
    return {"ruff": FakeRuff(objections=("would reformat: scripts/dev/with_test_env.py",))}


def _abort_at_verify(pickup_root: Path) -> dict:
    return {"verify": True, "verify_runner": FakeVerify(ok=False)}


def _abort_at_push(pickup_root: Path) -> dict:
    _pre_push_refusing(pickup_root)
    return {}


@pytest.mark.parametrize(
    "abort", [_abort_before_commit, _abort_at_verify, _abort_at_push], ids=lambda f: f.__name__
)
def test_an_aborted_run_leaves_no_sync_branch_it_created(
    canon: Path, pickup: Path, tmp_path: Path, abort
):
    report, gh, _ruff, _reports = _apply(canon, pickup, tmp_path, **abort(pickup))
    assert report.outcomes[0].action == ABORTED, report.outcomes[0].detail
    assert gh.created == []
    assert _local_sync_branches(pickup) == []
    assert _registered_worktrees(pickup) == [pickup]
    assert _git(pickup, "branch", "--list", "--remote", f"origin/{SYNC_BRANCH_PREFIX}*") == ""


def test_a_deployed_run_keeps_the_sync_branch_it_pushed(canon: Path, pickup: Path, tmp_path: Path):
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path)
    assert report.outcomes[0].action == DEPLOYED
    branch = sync_branch_for(TODAY)
    assert _local_sync_branches(pickup) == [branch]
    assert _git(pickup, "rev-parse", branch) == _git(pickup, "rev-parse", f"origin/{branch}")


def test_an_abort_after_the_push_keeps_the_pushed_sync_branch(
    canon: Path, pickup: Path, tmp_path: Path
):
    report, _gh, _ruff, _reports = _apply(canon, pickup, tmp_path, gh=FailingGh())
    assert report.outcomes[0].action == ABORTED
    assert "gh pr create failed" in report.outcomes[0].detail
    branch = sync_branch_for(TODAY)
    assert _local_sync_branches(pickup) == [branch]
    assert _git(pickup, "rev-parse", branch) == _git(pickup, "rev-parse", f"origin/{branch}")
    assert _registered_worktrees(pickup) == [pickup]


def test_a_stale_tracking_ref_of_the_same_name_does_not_read_as_pushed(
    canon: Path, pickup: Path, tmp_path: Path
):
    # An earlier same-day sync, merged and deleted on GitHub, can leave its
    # tracking ref behind at an older commit than this run's.
    branch = sync_branch_for(TODAY)
    _git(pickup, "update-ref", f"refs/remotes/origin/{branch}", _git(pickup, "rev-parse", "main"))
    report, _gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=FakeVerify(ok=False)
    )
    assert report.outcomes[0].action == ABORTED
    assert _local_sync_branches(pickup) == []


class BranchMovingGit(GitCommand):
    """Real git that moves the branch to `moved_to` just before sow deletes it."""

    def __init__(self, moved_to: str) -> None:
        self.moved_to = moved_to

    def run(self, cwd: Path, *args: str) -> CommandResult:
        if args[:2] == ("update-ref", "-d"):
            super().run(cwd, "update-ref", args[2], self.moved_to)
        return super().run(cwd, *args)


def test_a_sync_branch_that_moved_after_sow_read_its_tip_is_not_deleted(
    canon: Path, pickup: Path, tmp_path: Path
):
    branch = sync_branch_for(TODAY)
    moved_to = _git(pickup, "rev-parse", "main")
    report, _gh, _ruff, _reports = _apply(
        canon,
        pickup,
        tmp_path,
        git=BranchMovingGit(moved_to),
        verify=True,
        verify_runner=FakeVerify(ok=False),
    )
    assert report.outcomes[0].action == ABORTED
    assert _local_sync_branches(pickup) == [branch]
    assert _git(pickup, "rev-parse", branch) == moved_to


def test_an_abort_leaves_a_sync_branch_that_existed_before_the_run(
    canon: Path, pickup: Path, tmp_path: Path
):
    branch = sync_branch_for(TODAY)
    _git(pickup, "branch", branch, "main")
    report, _gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=FakeVerify(ok=False)
    )
    assert report.outcomes[0].action == ABORTED
    assert _local_sync_branches(pickup) == [branch]
    assert _registered_worktrees(pickup) == [pickup]


def test_a_second_run_the_same_day_after_an_abort_deploys(
    canon: Path, pickup: Path, tmp_path: Path
):
    first, _gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, ruff=FakeRuff(objections=("would reformat: x.py",))
    )
    assert first.outcomes[0].action == ABORTED
    second, gh, _ruff, _reports = _apply(canon, pickup, tmp_path)
    assert second.outcomes[0].action == DEPLOYED, second.outcomes[0].detail
    assert len(gh.created) == 1
    assert _registered_worktrees(pickup) == [pickup]


def test_a_second_run_the_same_day_after_a_committed_abort_deploys(
    canon: Path, pickup: Path, tmp_path: Path
):
    first, _gh, _ruff, _reports = _apply(
        canon, pickup, tmp_path, verify=True, verify_runner=FakeVerify(ok=False)
    )
    assert first.outcomes[0].action == ABORTED
    second, gh, _ruff, _reports = _apply(canon, pickup, tmp_path, verify=True)
    assert second.outcomes[0].action == DEPLOYED, second.outcomes[0].detail
    assert len(gh.created) == 1


# --------------------------------------------------------------------------
# exit codes


def _report(action: str) -> SowReport:
    from oversteward.sow.apply import ContextOutcome

    return SowReport(
        date=TODAY,
        applied=True,
        outcomes=(ContextOutcome("pickup", action, (), "detail"),),
        members_checked=3,
        contexts_checked=1,
        without_checkout=(),
    )


def test_a_measured_plan_exits_zero_even_with_nothing_to_do():
    assert exit_code(_report(NO_OP)) == EXIT_MEASURED
    assert exit_code(_report(SKIPPED)) == EXIT_MEASURED
    assert exit_code(_report(DEPLOYED)) == EXIT_MEASURED


def test_a_failed_apply_step_exits_one():
    assert exit_code(_report(ABORTED)) == EXIT_APPLY_FAILED


def test_a_context_that_could_not_be_read_exits_two():
    assert exit_code(_report(UNREADABLE)) == EXIT_COULD_NOT_LOOK


# --------------------------------------------------------------------------
# --deploy-shared


def test_deploy_shared_skips_inbox_and_pycache(tmp_path: Path):
    source = tmp_path / "shared"
    _write(source, "souls/chestertron.md", "soul\n")
    _write(source, "inbox.md", "do not deploy\n")
    _write(source, "scripts/__pycache__/x.pyc", "junk\n")
    (tmp_path / "home").mkdir()
    target = tmp_path / "home" / "shared"
    (result,) = deploy_shared(source, [target])
    assert (target / "souls/chestertron.md").read_text(encoding="utf-8") == "soul\n"
    assert not (target / "inbox.md").exists()
    assert not (target / "scripts/__pycache__").exists()
    assert result.copied == 1
    assert result.skipped == 2
    assert result.reachable


def test_deploy_shared_never_deletes_target_only_files(tmp_path: Path):
    source = tmp_path / "shared"
    _write(source, "souls/chestertron.md", "soul\n")
    target = tmp_path / "home" / "shared"
    _write(target, "inbox.md", "live inbox\n")
    _write(target, "local-only.md", "keep me\n")
    deploy_shared(source, [target])
    assert (target / "inbox.md").read_text(encoding="utf-8") == "live inbox\n"
    assert (target / "local-only.md").read_text(encoding="utf-8") == "keep me\n"


def test_deploy_shared_reports_an_unreachable_home_rather_than_creating_it(tmp_path: Path):
    source = tmp_path / "shared"
    _write(source, "souls/chestertron.md", "soul\n")
    missing_home = tmp_path / "no-such-home" / "shared"
    (result,) = deploy_shared(source, [missing_home])
    assert result.reachable is False
    assert result.copied == 0
    assert not missing_home.exists()
