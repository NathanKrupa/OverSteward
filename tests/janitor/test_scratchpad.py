# ABOUTME: Tests for the scratchpad janitor — dead sessions' ~/.claude/tmp dirs pruned, live ones never.
# ABOUTME: A fake /proc and a fake tmp root under tmp_path drive every case; nothing real is touched.

"""A session dir may only be deleted when it is old *and* provably unused.

Every test builds its own tmp root and its own ``/proc`` under ``tmp_path``: a
fake process is a directory holding ``cwd``/``exe`` symlinks, an ``fd/``
directory of symlinks and a ``comm`` file, which is exactly the shape the real
``/proc/<pid>`` presents to ``readlink`` and ``listdir``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from oversteward.janitor import scratchpad
from oversteward.janitor.scratchpad import (
    EXIT_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    DiskStats,
    JanitorConfig,
    compact_advised,
    run_janitor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "ops" / "wsl"
NOW = 2_000_000_000.0
DAY = 86_400
SELF_PID = 4242
SLUG = "-home-natha-OverSteward"
U1 = "0a4997e9-4c5e-49fa-b838-d437ebc4c436"
U2 = "22f98233-ca4c-4a47-9b11-c0de42c3112d"
GB = 1_000_000_000


def _touch(path: Path, age_days: float, data: bytes = b"x" * 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    stamp = NOW - age_days * DAY
    os.utime(path, (stamp, stamp), follow_symlinks=False)
    return path


def _age_dir(path: Path, age_days: float) -> None:
    stamp = NOW - age_days * DAY
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "tmp" / "claude-1000"
    root.mkdir(parents=True)
    return root


def _cand(root: Path, uuid: str = U1, age_days: float = 30, slug: str = SLUG) -> Path:
    cand = root / slug / uuid
    _touch(cand / "scratchpad" / "notes.txt", age_days)
    _touch(cand / "tasks" / "t.output", age_days)
    return cand


def _proc(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "self").symlink_to(str(SELF_PID))  # /proc carries non-pid entries too
    (proc / "meminfo").write_text("MemTotal: 1 kB\n")
    return proc


def _pid(
    proc: Path,
    pid: int,
    *,
    cwd: Path | str = "/",
    exe: Path | str = "/usr/bin/bash",
    fds: tuple[Path | str, ...] = (),
    comm: str = "bash",
) -> Path:
    entry = proc / str(pid)
    (entry / "fd").mkdir(parents=True)
    (entry / "cwd").symlink_to(cwd)
    (entry / "exe").symlink_to(exe)
    (entry / "comm").write_text(comm + "\n")
    for number, target in enumerate(fds):
        (entry / "fd" / str(number)).symlink_to(target)
    return entry


def _no_disk() -> DiskStats:
    return DiskStats(c_free=None, vhdx_bytes=None, root_used=None)


def _run(root: Path, proc: Path, *, apply: bool = False, days: int = 7, uid: int | None = None):
    config = JanitorConfig(root=root, proc=proc, days=days, apply=apply)
    return run_janitor(
        config,
        now=NOW,
        self_pid=SELF_PID,
        uid=os.getuid() if uid is None else uid,
        disk=_no_disk,
    )


def _render(outcome) -> str:
    return scratchpad.render(outcome)


def _row(text: str, uuid: str) -> str:
    rows = [line for line in text.splitlines() if uuid in line]
    assert len(rows) == 1, text
    return rows[0]


def _snapshot(tree: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(tree)): p.read_bytes()
        for p in sorted(tree.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


# --- liveness -------------------------------------------------------------------


class TestLiveness:
    def test_an_open_fd_under_the_candidate_keeps_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 100, fds=(cand / "tasks",))
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert cand.is_dir()
        assert "LIVE" in _row(_render(outcome), U1)
        assert "pid 100" in _row(_render(outcome), U1)

    def test_a_cwd_inside_the_candidate_keeps_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 101, cwd=cand / "scratchpad" / "x")
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert "LIVE" in _row(_render(outcome), U1)

    def test_an_exe_inside_the_candidate_keeps_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 102, exe=f"{cand / 'scratchpad' / 'bin'} (deleted)")
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert "LIVE" in _row(_render(outcome), U1)

    def test_a_sibling_whose_name_extends_the_candidate_does_not_keep_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 103, cwd=f"{cand}-other")
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_path_in_a_sibling_of_the_root_holds_nothing(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 108, cwd=f"{root}x{SLUG}/{U1}")
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_claude_holding_only_a_sibling_of_the_root_is_still_blind(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 109, comm="claude", fds=(f"{root}-old/{SLUG}/{U2}/tasks",))
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()

    def test_the_janitor_itself_never_keeps_a_candidate_alive(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, SELF_PID, cwd=cand / "scratchpad")
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert not cand.exists()
        assert "PRUNED" in _row(_render(outcome), U1)

    def test_a_same_uid_process_whose_fds_cannot_be_read_fails_closed(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        before = _snapshot(root)
        entry = _pid(proc, 104)
        (entry / "fd").chmod(0o000)
        try:
            outcome = _run(root, proc, apply=True)
        finally:
            (entry / "fd").chmod(0o755)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()
        assert _snapshot(root) == before
        assert "pid 104" in _render(outcome)

    def test_another_uids_unreadable_process_is_not_a_blind_spot(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        entry = _pid(proc, 105)
        (entry / "fd").chmod(0o000)
        try:
            outcome = _run(root, proc, apply=True, uid=os.getuid() + 1)
        finally:
            (entry / "fd").chmod(0o755)
        assert outcome.exit_code == EXIT_OK
        assert not cand.exists()

    @pytest.mark.skipif(
        not sys.platform.startswith("linux") or os.getuid() == 0,
        reason="needs Linux /proc and a non-root uid for the kernel to withhold fd",
    )
    def test_a_non_dumpable_process_of_this_uid_is_named_not_blind(self, tmp_path):
        # PR_SET_DUMPABLE=0 makes the kernel hand /proc/<pid>/fd to root, as it
        # does for (sd-pam) under systemd --user. The fake entry links to it.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import ctypes, time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); "
                "print('ready', flush=True); time.sleep(60)",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert child.stdout.readline().strip() == "ready"
            root, proc = _root(tmp_path), _proc(tmp_path)
            cand = _cand(root)
            (proc / str(child.pid)).symlink_to(f"/proc/{child.pid}")
            outcome = _run(root, proc, apply=True)
        finally:
            child.kill()
            child.wait()
        assert outcome.exit_code == EXIT_OK
        assert not cand.exists()
        withheld = [line for line in _render(outcome).splitlines() if "not inspected" in line]
        assert withheld and f"pid {child.pid}" in withheld[0]

    def test_a_claude_process_holding_nothing_under_the_root_means_the_scan_is_blind(
        self, tmp_path
    ):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _pid(proc, 106, comm="claude", cwd="/home/natha/OverSteward", fds=("/dev/null",))
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()
        assert "claude" in _render(outcome)
        assert "pid 106" in _render(outcome)

    def test_a_claude_process_holding_its_own_session_lets_the_scan_proceed(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        old = _cand(root, U1)
        own = _cand(root, U2, age_days=0)
        _pid(proc, 107, comm="claude", fds=(own / "tasks",))
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert not old.exists()
        assert own.is_dir()

    def test_a_session_that_resumes_after_the_scan_is_seen_before_the_delete(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)

        def _resume_then_measure() -> DiskStats:
            # The disk probe runs after the first /proc read and before the
            # sweep, so a process appearing here is one the first read missed.
            _pid(proc, 110, fds=(cand / "tasks",))
            return _no_disk()

        outcome = run_janitor(
            JanitorConfig(root=root, proc=proc, apply=True),
            now=NOW,
            self_pid=SELF_PID,
            uid=os.getuid(),
            disk=_resume_then_measure,
        )
        assert cand.is_dir()
        row = _row(_render(outcome), U1)
        assert "LIVE" in row
        assert "re-check" in row
        assert "pid 110" in row

    def test_a_scan_that_goes_blind_before_the_delete_deletes_nothing(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        entries: list[Path] = []

        def _blind_then_measure() -> DiskStats:
            entry = _pid(proc, 111)
            (entry / "fd").chmod(0o000)
            entries.append(entry)
            return _no_disk()

        try:
            outcome = run_janitor(
                JanitorConfig(root=root, proc=proc, apply=True),
                now=NOW,
                self_pid=SELF_PID,
                uid=os.getuid(),
                disk=_blind_then_measure,
            )
        finally:
            for entry in entries:
                (entry / "fd").chmod(0o755)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()
        assert "re-check blind" in _row(_render(outcome), U1)

    def test_a_missing_proc_root_is_could_not_look(self, tmp_path):
        root = _root(tmp_path)
        cand = _cand(root)
        outcome = _run(root, tmp_path / "no-proc", apply=True)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()


# --- candidates and age -----------------------------------------------------------


class TestCandidates:
    def test_age_is_the_newest_file_not_the_directory(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root, age_days=30)
        _touch(cand / "scratchpad" / "gs" / ".git" / "objects" / "pack" / "p.pack", 1)
        for path in [cand, *(p for p in cand.rglob("*") if p.is_dir())]:
            _age_dir(path, 30)
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        row = _row(_render(outcome), U1)
        assert "KEPT" in row
        assert "p.pack" in row

    def test_exactly_the_threshold_is_old_enough(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root, age_days=7)
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_day_short_of_the_threshold_is_kept(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root, age_days=6.9)
        _run(root, proc, apply=True)
        assert cand.is_dir()

    def test_a_dir_that_is_not_a_uuid_is_unrecognised_and_left_alone(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        odd = root / SLUG / "base1"
        _touch(odd / "f.txt", 40)
        _touch(root / "ruff.txt", 40)
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert odd.is_dir()
        assert (root / "ruff.txt").is_file()
        assert "unrecognised 2" in _render(outcome)

    def test_a_uuid_named_symlink_is_never_followed_or_deleted(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        elsewhere = tmp_path / "precious"
        _touch(elsewhere / "keep.txt", 40)
        (root / SLUG).mkdir()
        (root / SLUG / U1).symlink_to(elsewhere)
        outcome = _run(root, proc, apply=True)
        assert (elsewhere / "keep.txt").is_file()
        assert (root / SLUG / U1).is_symlink()
        assert "unrecognised 1" in _render(outcome)

    def test_a_symlink_inside_a_pruned_candidate_does_not_take_its_target(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        elsewhere = _touch(tmp_path / "precious" / "keep.txt", 40)
        cand = _cand(root)
        (cand / "scratchpad" / "link").symlink_to(elsewhere.parent)
        _run(root, proc, apply=True)
        assert not cand.exists()
        assert elsewhere.is_file()

    def test_an_unreadable_subdir_keeps_the_candidate_and_fails(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        locked = cand / "scratchpad" / "locked"
        _touch(locked / "new.txt", 0)
        locked.chmod(0o000)
        try:
            outcome = _run(root, proc, apply=True)
        finally:
            locked.chmod(0o755)
        assert outcome.exit_code == EXIT_FAILED
        assert cand.is_dir()
        assert "UNREADABLE" in _row(_render(outcome), U1)


# --- registered worktrees ---------------------------------------------------------


def _age_tree(tree: Path, age_days: float) -> None:
    """Backdate every file and directory under ``tree``, links included, to ``age_days``."""
    for path in [*tree.rglob("*"), tree]:
        _age_dir(path, age_days)


def _git(*args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
        check=True,
        capture_output=True,
    )


def _clone_with_worktree(clone: Path, worktree: Path) -> None:
    """A real repository at ``clone`` with a linked worktree at ``worktree`` holding a commit."""
    _git("init", "-q", str(clone))
    _git("-C", str(clone), "commit", "-q", "--allow-empty", "-m", "base")
    _git("-C", str(clone), "worktree", "add", "-q", "-b", "feat", str(worktree))
    (worktree / "work.txt").write_text("unpushed")
    _git("-C", str(worktree), "add", "work.txt")
    _git("-C", str(worktree), "commit", "-q", "-m", "unpushed work")


class TestGitLinks:
    def test_a_git_file_naming_a_live_repo_outside_skips_the_candidate(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        registry = tmp_path / "repo" / ".git" / "worktrees" / "child"
        registry.mkdir(parents=True)
        _touch(cand / "scratchpad" / "wt" / "child" / ".git", 40, f"gitdir: {registry}\n".encode())
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert cand.is_dir()
        row = _row(_render(outcome), U1)
        assert "SKIPPED" in row
        assert f"worktree_doctor.py teardown {cand / 'scratchpad' / 'wt' / 'child'}" in row

    def test_a_git_file_whose_repo_is_gone_ties_nothing_and_is_pruned(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        gone = tmp_path / "repo" / ".git" / "worktrees" / "child"
        _touch(cand / "scratchpad" / "wt" / "child" / ".git", 40, f"gitdir: {gone}\n".encode())
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_git_file_naming_a_repo_in_the_same_candidate_is_pruned(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _touch(cand / "scratchpad" / "main" / ".git" / "worktrees" / "child" / "HEAD", 40)
        _touch(
            cand / "scratchpad" / "child" / ".git", 40, b"gitdir: ../main/.git/worktrees/child\n"
        )
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_an_unparseable_git_file_keeps_the_candidate(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _touch(cand / "scratchpad" / "odd" / ".git", 40, b"not a link\n")
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert "SKIPPED" in _row(_render(outcome), U1)

    def test_a_git_directory_with_no_linked_worktree_is_pruned(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _touch(cand / "scratchpad" / "clone" / ".git" / "HEAD", 40)
        outcome = _run(root, proc, apply=True)
        assert not cand.exists()
        assert "PRUNED" in _row(_render(outcome), U1)

    def test_a_clone_whose_linked_worktree_lives_outside_is_kept(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        outside = tmp_path / "outside"
        _clone_with_worktree(cand / "scratchpad" / "clone", outside)
        _age_tree(cand, 30)
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert cand.is_dir()
        row = _row(_render(outcome), U1)
        assert "SKIPPED" in row
        assert f"linked worktree at {outside}" in row
        assert row.endswith(f"worktree_doctor.py teardown {outside}")
        log = subprocess.run(
            ["git", "-C", str(outside), "log", "--format=%s", "-1"], capture_output=True, text=True
        )
        assert log.stdout.strip() == "unpushed work"

    def test_a_clone_and_its_worktree_both_inside_go_together(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _clone_with_worktree(cand / "scratchpad" / "clone", cand / "scratchpad" / "wt")
        _age_tree(cand, 30)
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_clone_whose_outside_worktree_was_removed_is_pruned(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        outside = tmp_path / "outside"
        _clone_with_worktree(cand / "scratchpad" / "clone", outside)
        shutil.rmtree(outside)
        _age_tree(cand, 30)
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_relative_git_file_link_resolves_from_its_own_directory(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        registry = tmp_path / "repo" / ".git" / "worktrees" / "child"
        registry.mkdir(parents=True)
        link = cand / "scratchpad" / "wt" / "child" / ".git"
        relative = os.path.relpath(registry, link.parent)
        _touch(link, 40, f"gitdir: {relative}\n".encode())
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert "SKIPPED" in _row(_render(outcome), U1)

    def test_an_outside_tie_after_an_inside_pair_is_still_found(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        pair = cand / "scratchpad" / "a-pair"
        _clone_with_worktree(pair / "clone", pair / "wt")
        outside = tmp_path / "outside"
        _clone_with_worktree(cand / "scratchpad" / "z-clone", outside)
        _age_tree(cand, 30)
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert f"linked worktree at {outside}" in _row(_render(outcome), U1)


class TestRepositories:
    def test_a_separate_git_dir_whose_checkout_is_outside_is_kept(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        outside = tmp_path / "outside"
        _git("init", "-q", "--separate-git-dir", str(cand / "scratchpad" / "gd"), str(outside))
        (outside / "work.txt").write_text("unpushed")
        _git("-C", str(outside), "add", "work.txt")
        _git("-C", str(outside), "commit", "-q", "-m", "unpushed work")
        _age_tree(cand, 30)
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert cand.is_dir()
        assert "separate git dir" in _row(_render(outcome), U1)
        log = subprocess.run(
            ["git", "-C", str(outside), "log", "--format=%s", "-1"], capture_output=True, text=True
        )
        assert log.stdout.strip() == "unpushed work"

    def test_a_separate_git_dir_whose_checkout_is_inside_goes_with_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        inside = cand / "scratchpad" / "checkout"
        _git("init", "-q", "--separate-git-dir", str(cand / "scratchpad" / "gd"), str(inside))
        _age_tree(cand, 30)
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_bare_repository_with_no_worktrees_is_pruned(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        _git("init", "-q", "--bare", str(cand / "scratchpad" / "mirror.git"))
        _age_tree(cand, 30)
        _run(root, proc, apply=True)
        assert not cand.exists()

    def test_a_core_worktree_outside_keeps_the_candidate(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        outside = tmp_path / "outside"
        outside.mkdir()
        repo = cand / "scratchpad" / "r"
        _git("init", "-q", str(repo))
        _git("-C", str(repo), "config", "core.worktree", str(outside))
        _age_tree(cand, 30)
        outcome = _run(root, proc, apply=True)
        assert cand.is_dir()
        assert f"has its checkout at {outside}" in _row(_render(outcome), U1)

    def test_a_submodule_inside_its_superproject_goes_with_it(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        source = tmp_path / "subsource"
        _git("init", "-q", str(source))
        _git("-C", str(source), "commit", "-q", "--allow-empty", "-m", "sub")
        top = cand / "scratchpad" / "top"
        _git("init", "-q", str(top))
        _git("-C", str(top), "-c", "protocol.file.allow=always", "submodule", "add", "-q",
             str(source), "sub")
        _age_tree(cand, 30)
        outcome = _run(root, proc, apply=True)
        assert outcome.exit_code == EXIT_OK
        assert not cand.exists()

    def test_an_unreadable_repository_config_keeps_the_candidate(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        gd = cand / "scratchpad" / "gd"
        _touch(gd / "HEAD", 40, b"ref: refs/heads/main\n")
        _touch(gd / "objects" / "info" / "packs", 40)
        config = _touch(gd / "config", 40, b"[core]\n\tbare = false\n")
        config.chmod(0o000)
        try:
            outcome = _run(root, proc, apply=True)
        finally:
            config.chmod(0o644)
        assert cand.is_dir()
        assert "unreadable git config" in _row(_render(outcome), U1)


# --- dry run, apply, failure ----------------------------------------------------


class TestApply:
    def test_without_apply_nothing_changes_and_the_verdict_is_would_prune(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        _cand(root)
        before = _snapshot(root)
        outcome = _run(root, proc)
        assert outcome.exit_code == EXIT_OK
        assert _snapshot(root) == before
        text = _render(outcome)
        assert "WOULD-PRUNE" in _row(text, U1)
        assert "would free" in text

    def test_a_child_that_cannot_be_removed_is_a_partial_failure(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _cand(root)
        stuck = cand / "scratchpad" / "stuck"
        _touch(stuck / "f.txt", 40)
        stuck.chmod(0o500)
        try:
            outcome = _run(root, proc, apply=True)
        finally:
            stuck.chmod(0o755)
        assert outcome.exit_code == EXIT_FAILED
        assert "PARTIAL" in _row(_render(outcome), U1)
        assert outcome.headline.startswith("PARTIAL")

    def test_totals_count_every_verdict(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        _cand(root, U1)
        live = _cand(root, U2)
        _pid(proc, 100, fds=(live / "tasks",))
        _touch(root / SLUG / "base1" / "f", 40)
        text = _render(_run(root, proc))
        assert "would-free" in text
        assert "1 dirs" in text
        assert "live 1" in text
        assert "unrecognised 1" in text


# --- the root ------------------------------------------------------------------


class TestRoot:
    def test_a_missing_root_is_not_configured(self, tmp_path):
        outcome = _run(tmp_path / "absent", _proc(tmp_path), apply=True)
        assert outcome.exit_code == EXIT_NOT_CONFIGURED

    def test_a_symlinked_root_is_not_configured_and_its_target_survives(self, tmp_path):
        real = _root(tmp_path)
        cand = _cand(real)
        link = tmp_path / "link-root"
        link.symlink_to(real)
        outcome = _run(link, _proc(tmp_path), apply=True)
        assert outcome.exit_code == EXIT_NOT_CONFIGURED
        assert cand.is_dir()

    def test_a_root_that_is_a_file_is_not_configured(self, tmp_path):
        path = tmp_path / "file"
        path.write_text("x")
        assert _run(path, _proc(tmp_path)).exit_code == EXIT_NOT_CONFIGURED

    @pytest.mark.parametrize("days", [0, -3])
    def test_fewer_than_one_day_is_refused(self, tmp_path, days):
        root = _root(tmp_path)
        cand = _cand(root, age_days=40)
        outcome = _run(root, _proc(tmp_path), apply=True, days=days)
        assert outcome.exit_code == EXIT_NOT_CONFIGURED
        assert cand.is_dir()


# --- the disk lines ---------------------------------------------------------------


class TestDisk:
    @pytest.mark.parametrize(
        ("vhdx", "used", "advised"),
        [(180, 125, True), (130, 125, False), (145, 125, False), (146, 125, True)],
    )
    def test_compaction_is_advised_only_past_twenty_gb_of_slack(self, vhdx, used, advised):
        assert compact_advised(vhdx * GB, used * GB) is advised

    def test_the_report_carries_the_advice_and_the_free_space(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        config = JanitorConfig(root=root, proc=proc)
        outcome = run_janitor(
            config,
            now=NOW,
            self_pid=SELF_PID,
            uid=os.getuid(),
            disk=lambda: DiskStats(c_free=28 * GB, vhdx_bytes=180 * GB, root_used=125 * GB),
        )
        text = _render(outcome)
        assert "COMPACT ADVISED" in text
        assert "/mnt/c free: 28.0 GB" in text
        assert "ext4.vhdx: 180.0 GB" in text

    def test_no_advice_when_the_vhdx_is_close_to_used(self, tmp_path):
        root, proc = _root(tmp_path), _proc(tmp_path)
        outcome = run_janitor(
            JanitorConfig(root=root, proc=proc),
            now=NOW,
            self_pid=SELF_PID,
            uid=os.getuid(),
            disk=lambda: DiskStats(c_free=28 * GB, vhdx_bytes=130 * GB, root_used=125 * GB),
        )
        assert "COMPACT ADVISED" not in _render(outcome)

    def test_an_unmeasured_disk_says_so(self, tmp_path):
        text = _render(_run(_root(tmp_path), _proc(tmp_path)))
        assert "ext4.vhdx: unmeasured" in text
        assert "COMPACT ADVISED" not in text


# --- the entry point -------------------------------------------------------------


def _entrypoint():
    spec = importlib.util.spec_from_file_location(
        "scratchpad_janitor", REPO_ROOT / "scripts" / "scratchpad_janitor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEntrypoint:
    def test_a_missing_root_exits_2(self, tmp_path, capsys):
        code = _entrypoint().main(["--root", str(tmp_path / "absent"), "--proc", str(tmp_path)])
        assert code == EXIT_NOT_CONFIGURED
        assert capsys.readouterr().out.startswith("NOT CONFIGURED")

    def test_a_dry_run_prints_the_report_and_deletes_nothing(self, tmp_path, capsys):
        root, proc = _root(tmp_path), _proc(tmp_path)
        cand = _touch(root / SLUG / U1 / "f.txt", 4000)
        code = _entrypoint().main(["--root", str(root), "--proc", str(proc)])
        assert code == EXIT_OK
        assert cand.is_file()
        assert "WOULD-PRUNE" in capsys.readouterr().out

    def test_a_crash_is_a_failure_never_ok(self, monkeypatch, capsys):
        def _explode(*_args, **_kwargs):
            raise RuntimeError("proc vanished")

        monkeypatch.setattr(scratchpad, "run_janitor", _explode)
        assert _entrypoint().main([]) == EXIT_FAILED
        assert capsys.readouterr().out.startswith("FAILED - scratchpad janitor crashed")


# --- systemd units ------------------------------------------------------------------


def _directives(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(
        line.split("=", 1) for line in lines if "=" in line and not line.startswith("#")
    )


class TestUnits:
    def test_timer_runs_daily_at_half_past_two_and_catches_up(self):
        timer = _directives(OPS / "scratchpad-janitor.timer")
        assert timer["OnCalendar"] == "*-*-* 02:30:00"
        assert timer["Persistent"] == "true"

    def test_service_is_a_low_priority_oneshot_that_applies(self):
        service = _directives(OPS / "scratchpad-janitor.service")
        assert service["Type"] == "oneshot"
        assert service["ExecStart"] == (
            "/home/natha/OverSteward/.venv/bin/python "
            "/home/natha/OverSteward/scripts/scratchpad_janitor.py --apply"
        )
        assert service["Nice"] == "10"
        assert service["IOSchedulingClass"] == "idle"

    @pytest.mark.parametrize("name", ["scratchpad-janitor.service", "scratchpad-janitor.timer"])
    def test_units_open_with_aboutme(self, name):
        first = (OPS / name).read_text(encoding="utf-8").splitlines()[:2]
        assert all(line.startswith("# ABOUTME: ") for line in first)
