# ABOUTME: Shared fixtures for the dream CLI tests that take the run lock: a live foreign holder,
# ABOUTME: and a guard that points the lock defaults at a sentinel so no test can reach the live lock.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from oversteward.dream import runlock


@pytest.fixture
def never_the_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the defaults at a sentinel, so a test that forgets --lock/--runs fails loudly."""
    sentinel = tmp_path / "default-must-not-exist"
    monkeypatch.setattr(runlock, "DEFAULT_LOCK_PATH", sentinel / "dream_run.lock")
    monkeypatch.setattr(runlock, "DEFAULT_RUNS_PATH", sentinel / "dream_runs.jsonl")
    yield
    assert not sentinel.exists()


@pytest.fixture
def foreign():
    """A live process that is not this test's holder, recorded as the lock's holder."""
    proc = subprocess.Popen(["sleep", "60"])
    try:
        start = runlock.proc_start_time(proc.pid)
        assert start is not None
        yield {
            "pid": proc.pid,
            "start": start,
            "trigger": "timer",
            "started_at": "2026-11-11T03:30:00+00:00",
        }
    finally:
        proc.kill()
        proc.wait()
