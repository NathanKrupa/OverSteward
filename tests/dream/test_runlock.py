# ABOUTME: Tests for the dream cycle's run lock service — holder record, liveness, reclaim, flock, run ledger.
# ABOUTME: Liveness is a fake probe and /proc is a fake tree; every lock and ledger path is a temp file.

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import pytest

from oversteward.dream import runlock
from oversteward.dream.runlock import Holder, Locked, LockUnreadable, RunLock

ME = Holder(pid=42, start=7, comm="claude")
OTHER = Holder(pid=500, start=111, comm="claude")
FOREIGN_RECORD = {
    "pid": OTHER.pid,
    "start": OTHER.start,
    "trigger": "timer",
    "started_at": "2026-11-11T03:30:00+00:00",
}


def _probe(alive: dict[int, int]):
    """A liveness probe over a fixed table: pid -> start time, absent pid -> None."""
    return lambda pid: alive.get(pid)


def _lock(tmp_path: Path, alive: dict[int, int], **kwargs) -> RunLock:
    return RunLock(tmp_path / "dream_run.lock", tmp_path / "dream_runs.jsonl", probe=_probe(alive), **kwargs)


def _rows(lock: RunLock) -> list[dict]:
    if not lock.runs_path.exists():
        return []
    return [json.loads(line) for line in lock.runs_path.read_text().splitlines() if line.strip()]


def _record(lock: RunLock) -> dict | None:
    text = lock.lock_path.read_text() if lock.lock_path.exists() else ""
    return json.loads(text) if text.strip() else None


def _seed(lock: RunLock, record: dict) -> bytes:
    lock.lock_path.write_text(json.dumps(record))
    return lock.lock_path.read_bytes()


# ---- ensure: the four record states -----------------------------------------


def test_empty_lock_is_acquired_with_a_started_row(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})
    assert lock.ensure(ME, "session") is True
    record = _record(lock)
    assert (record["pid"], record["start"], record["trigger"]) == (ME.pid, ME.start, "session")
    assert [r["event"] for r in _rows(lock)] == ["started"]


def test_live_foreign_holder_refuses_and_records_a_skip(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start, OTHER.pid: OTHER.start})
    before = _seed(lock, FOREIGN_RECORD)
    with pytest.raises(Locked) as exc:
        lock.ensure(ME, "session")
    message = str(exc.value)
    assert "500" in message and "timer" in message and "2026-11-11T03:30:00" in message
    assert lock.lock_path.read_bytes() == before
    rows = _rows(lock)
    assert [r["event"] for r in rows] == ["skipped"]
    assert rows[0]["reason"] == "locked by 500"
    assert rows[0]["pid"] == ME.pid and rows[0]["trigger"] == "session"


def test_dead_holder_is_reclaimed_and_the_reclaim_names_it(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})  # 500 reads as gone
    _seed(lock, FOREIGN_RECORD)
    assert lock.ensure(ME, "session") is True
    assert _record(lock)["pid"] == ME.pid
    rows = _rows(lock)
    assert [r["event"] for r in rows] == ["reclaimed", "started"]
    assert "500" in rows[0]["reason"]


def test_recycled_pid_is_reclaimed(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start, OTHER.pid: 999})  # pid alive, another process
    _seed(lock, FOREIGN_RECORD)
    assert lock.ensure(ME, "session") is True
    assert _record(lock)["pid"] == ME.pid
    assert [r["event"] for r in _rows(lock)] == ["reclaimed", "started"]


def test_same_holder_re_enters_without_touching_the_record(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})
    assert lock.ensure(ME, "session") is True
    first = lock.lock_path.read_bytes()
    assert lock.ensure(ME, "session") is False
    assert lock.lock_path.read_bytes() == first
    assert [r["event"] for r in _rows(lock)] == ["started"]


# ---- ensure: could not look --------------------------------------------------


def test_garbage_record_is_unreadable_not_free(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})
    lock.lock_path.write_text("not json {")
    before = lock.lock_path.read_bytes()
    with pytest.raises(LockUnreadable) as exc:
        lock.ensure(ME, "session")
    assert "could not read" in str(exc.value)
    assert lock.lock_path.read_bytes() == before


def test_blind_liveness_is_unreadable_not_dead(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {})  # the probe cannot see even the caller
    before = _seed(lock, FOREIGN_RECORD)
    with pytest.raises(LockUnreadable) as exc:
        lock.ensure(ME, "session")
    assert "could not read" in str(exc.value)
    assert lock.lock_path.read_bytes() == before


def test_acquire_waits_on_the_flock_and_gives_up_unreadable(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start}, wait_seconds=0.05)
    fd = os.open(lock.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(LockUnreadable) as exc:
            lock.ensure(ME, "session")
    finally:
        os.close(fd)
    assert "could not read" in str(exc.value)
    assert lock.lock_path.read_bytes() == b""


# ---- release -----------------------------------------------------------------


def test_release_empties_the_record_and_closes_the_run(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})
    lock.ensure(ME, "session")
    lock.release(ME, "completed", count=3)
    assert lock.lock_path.read_bytes() == b""
    rows = _rows(lock)
    assert [r["event"] for r in rows] == ["started", "completed"]
    assert rows[1]["count"] == 3


def test_release_by_another_holder_refuses(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start, OTHER.pid: OTHER.start})
    before = _seed(lock, FOREIGN_RECORD)
    with pytest.raises(Locked):
        lock.release(ME, "ended", reason="abort")
    assert lock.lock_path.read_bytes() == before


def test_every_row_carries_pid_trigger_timestamp_and_count(tmp_path: Path) -> None:
    lock = _lock(tmp_path, {ME.pid: ME.start})
    lock.ensure(ME, "manual")
    lock.release(ME, "ended", reason="ledger current")
    for row in _rows(lock):
        assert {"event", "pid", "trigger", "at", "count"} <= row.keys()
    assert _rows(lock)[1]["reason"] == "ledger current"
    assert _rows(lock)[1]["count"] == 0


# ---- holder discovery over /proc --------------------------------------------


def _stat_line(pid: int, comm: str, ppid: int, start: int) -> str:
    # Fields 3..22 after the comm: state, ppid, 17 fillers, starttime (field 22).
    return f"{pid} ({comm}) S {ppid} " + "0 " * 17 + f"{start} 0 0 0 0 0\n"


def _fake_proc(root: Path, tree: list[tuple[int, str, int, int]]) -> Path:
    for pid, comm, ppid, start in tree:
        (root / str(pid)).mkdir(parents=True)
        (root / str(pid) / "stat").write_text(_stat_line(pid, comm, ppid, start))
    return root


def test_parse_stat_splits_on_the_last_paren() -> None:
    stat = runlock.parse_stat(_stat_line(123, "a b) c", 45, 6789))
    assert (stat.pid, stat.comm, stat.ppid, stat.start) == (123, "a b) c", 45, 6789)


def test_holder_is_the_nearest_claude_ancestor(tmp_path: Path) -> None:
    proc = _fake_proc(
        tmp_path / "proc",
        [
            (100, "python", 90, 1000),
            (90, "bash", 80, 900),
            (80, "claude", 70, 800),
            (70, "MainThread", 1, 700),
            (1, "init", 0, 1),
        ],
    )
    holder = runlock.discover_holder(100, proc_root=proc)
    assert (holder.pid, holder.start, holder.comm) == (80, 800, "claude")


def test_holder_without_a_claude_ancestor_is_the_direct_parent(tmp_path: Path) -> None:
    proc = _fake_proc(
        tmp_path / "proc",
        [(100, "python", 90, 1000), (90, "bash", 1, 900), (1, "init", 0, 1)],
    )
    holder = runlock.discover_holder(100, proc_root=proc)
    assert (holder.pid, holder.start, holder.comm) == (90, 900, "bash")


def test_holder_discovery_without_proc_is_unreadable(tmp_path: Path) -> None:
    with pytest.raises(LockUnreadable):
        runlock.discover_holder(100, proc_root=tmp_path / "no-proc")


def test_proc_start_time_reads_a_live_pid_and_none_for_a_gone_one(tmp_path: Path) -> None:
    assert isinstance(runlock.proc_start_time(os.getpid()), int)
    assert runlock.proc_start_time(100, proc_root=tmp_path) is None


def test_default_trigger_prefers_the_environment_then_the_holder() -> None:
    bash = Holder(pid=1, start=1, comm="bash")
    assert runlock.default_trigger(ME, {runlock.TRIGGER_ENV: "timer"}) == "timer"
    assert runlock.default_trigger(ME, {}) == "session"
    assert runlock.default_trigger(bash, {}) == "manual"
