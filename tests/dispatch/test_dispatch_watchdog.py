# ABOUTME: Tests for the dispatch watchdog — the silent-loop guard.
# ABOUTME: Pure progress truth table + branch_exists with injected runner + watch() loop flow.

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path


def _load_watchdog():
    """Load the script by file path (no install needed)."""
    rel = Path("scripts") / "dispatch" / "dispatch_watchdog.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("dispatch_watchdog", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


wd = _load_watchdog()


# --- assess_dispatch_progress: the truth table ----------------------------


def test_pushed_branch_is_progressing_no_alert():
    verdict = wd.assess_dispatch_progress(elapsed_min=3, branch_present=True, warn_min=22)
    assert verdict.status == "progressing"
    assert verdict.should_alert is False


def test_pushed_branch_progressing_even_past_warn_window():
    # A branch that appears after the warn threshold is still healthy, not a stall.
    verdict = wd.assess_dispatch_progress(elapsed_min=30, branch_present=True, warn_min=22)
    assert verdict.status == "progressing"
    assert verdict.should_alert is False


def test_no_branch_before_warn_is_watching_no_alert():
    verdict = wd.assess_dispatch_progress(elapsed_min=10, branch_present=False, warn_min=22)
    assert verdict.status == "watching"
    assert verdict.should_alert is False


def test_no_branch_at_warn_threshold_is_stalled_and_alerts():
    verdict = wd.assess_dispatch_progress(elapsed_min=22, branch_present=False, warn_min=22)
    assert verdict.status == "stalled"
    assert verdict.should_alert is True


def test_no_branch_past_warn_threshold_is_stalled_and_alerts():
    verdict = wd.assess_dispatch_progress(elapsed_min=45, branch_present=False, warn_min=22)
    assert verdict.status == "stalled"
    assert verdict.should_alert is True


# --- branch_exists: injected runner ---------------------------------------


@dataclass
class _FakeResult:
    stdout: str


def test_branch_exists_true_when_ls_remote_returns_a_ref():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeResult(stdout="abc123\trefs/heads/feat/issue-947-foo\n")

    assert wd.branch_exists("NathanKrupa/aigranthelper", 947, runner=runner) is True
    # probes the right remote + ref glob
    assert calls[0][:2] == ["git", "ls-remote"]
    assert "https://github.com/NathanKrupa/aigranthelper.git" in calls[0]
    assert "refs/heads/*issue-947*" in calls[0]


def test_branch_exists_false_on_empty_output():
    assert wd.branch_exists("o/r", 1, runner=lambda cmd, **k: _FakeResult(stdout="\n")) is False


def test_branch_exists_false_on_probe_error_does_not_raise():
    def boom(cmd, **kwargs):
        raise OSError("network down")

    # A failed probe is "no branch yet", not a crash — the next poll retries.
    assert wd.branch_exists("o/r", 1, runner=boom) is False


# --- watch(): the poll loop with injected clock/sleep/branch_check --------


def test_watch_returns_progressing_as_soon_as_branch_appears():
    # Branch absent on probe 1, present on probe 2.
    presence = iter([False, True])
    slept = []
    ticks = iter([0.0, 0.0, 60.0])  # start, probe1, probe2 (1 min later)

    verdict = wd.watch(
        "o/r",
        947,
        warn_min=22,
        poll_sec=60,
        branch_check=lambda fn, n: next(presence),
        sleeper=lambda s: slept.append(s),
        clock=lambda: next(ticks),
    )
    assert verdict.status == "progressing"
    assert slept == [60]  # slept once between the two probes


def test_watch_alerts_when_warn_window_elapses_with_no_branch():
    slept = []
    # start=0, then probe at 10m (watching), probe at 25m (stalled → return)
    ticks = iter([0.0, 600.0, 1500.0])

    verdict = wd.watch(
        "o/r",
        947,
        warn_min=22,
        poll_sec=60,
        branch_check=lambda fn, n: False,
        sleeper=lambda s: slept.append(s),
        clock=lambda: next(ticks),
    )
    assert verdict.status == "stalled"
    assert verdict.should_alert is True
    assert slept == [60]  # one quiet poll before the stall verdict
