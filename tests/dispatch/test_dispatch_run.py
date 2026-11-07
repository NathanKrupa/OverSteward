# ABOUTME: Tests for oversteward.dispatch_run — a subagent held on an `ask` prompt, and a measured duration.
# ABOUTME: Fixtures follow the AG#2736 transcript's shape; one test reads the real capture when it is on disk.

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oversteward import dispatch_run

FIXTURE = Path(__file__).parent / "fixtures" / "ag2736-subagent.jsonl"

#: The real AG#2736 subagent transcript, on the machine that captured it. It is
#: not committed: it holds a working session's full content.
REAL_CAPTURE = Path(
    "/home/natha/.claude/projects/-home-natha-OverSteward/"
    "59bdb217-7655-468d-8188-ae521880b907/subagents/agent-a47648315efc215b1.jsonl"
)

HELD_ID = "toolu_01AYTVU16mL6q4Xh7SF1EwxM"
ASKED_AT = datetime(2026, 11, 7, 3, 51, 55, 773000, tzinfo=UTC)
ANSWERED_AT = datetime(2026, 11, 7, 10, 36, 15, 476000, tzinfo=UTC)


def _load_cli():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dispatch" / "dispatch_run.py"
    spec = importlib.util.spec_from_file_location("dispatch_run_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


def _entries() -> list[dict]:
    return dispatch_run.read_entries(FIXTURE)


def _before_the_answer() -> list[dict]:
    """The transcript as it stood while the agent waited: everything before the result."""
    entries = _entries()
    cut = next(i for i, e in enumerate(entries) if e["timestamp"].startswith("2026-11-07T10:36:15"))
    return entries[:cut]


def _write(path: Path, entries: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


# --- the held prompt -------------------------------------------------------


def test_the_ag2736_hold_alerts_while_the_agent_waits():
    """The forced failure: the transcript at 10:30 UTC, six and a half hours into the hold."""
    now = datetime(2026, 11, 7, 10, 30, tzinfo=UTC)

    held = dispatch_run.blocked_prompts(_before_the_answer(), now, warn_min=10)

    assert [p.tool_use_id for p in held] == [HELD_ID]
    assert held[0].asked_at == ASKED_AT
    assert held[0].reason == "DESTRUCTIVE COMMAND — confirmation required"
    assert round(held[0].age_min(now)) == 398


def test_the_answered_prompt_is_not_held():
    """The whole transcript: the tool result arrived, so nothing is pending."""
    assert dispatch_run.pending_prompts(_entries()) == []


def test_a_prompt_younger_than_the_warning_is_not_reported():
    now = ASKED_AT + timedelta(minutes=9)

    assert dispatch_run.blocked_prompts(_before_the_answer(), now, warn_min=10) == []


def test_a_prompt_exactly_at_the_warning_is_reported():
    now = ASKED_AT + timedelta(minutes=10)

    assert len(dispatch_run.blocked_prompts(_before_the_answer(), now, warn_min=10)) == 1


def test_a_result_for_another_tool_call_does_not_answer_the_prompt():
    entries = _before_the_answer()
    entries.append(
        {
            "type": "user",
            "timestamp": "2026-11-07T04:00:00.000Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_other"}]},
        }
    )

    assert [p.tool_use_id for p in dispatch_run.pending_prompts(entries)] == [HELD_ID]


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_a_hook_that_did_not_ask_holds_nothing(decision):
    entries = _before_the_answer()
    attachment = entries[-1]["attachment"]
    output = json.loads(attachment["stdout"])
    output["hookSpecificOutput"]["permissionDecision"] = decision
    attachment["stdout"] = json.dumps(output)

    assert dispatch_run.pending_prompts(entries) == []


def test_an_ask_from_a_hook_on_another_event_holds_nothing():
    entries = _before_the_answer()
    entries[-1]["attachment"]["hookEvent"] = "PostToolUse"

    assert dispatch_run.pending_prompts(entries) == []


def test_a_half_written_last_line_is_dropped(tmp_path):
    path = _write(tmp_path / "t.jsonl", _before_the_answer())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "user", "timest')

    assert len(dispatch_run.read_entries(path)) == len(_before_the_answer())


def test_a_bad_line_mid_file_is_unreadable_not_clear(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('not json\n{"type": "user"}\n', encoding="utf-8")

    with pytest.raises(dispatch_run.TranscriptUnreadable):
        dispatch_run.read_entries(path)


# --- the sweep and the CLI ---------------------------------------------------


def _held_tree(root: Path) -> Path:
    """A projects root holding the AG#2736 transcript as it stood mid-hold."""
    path = root / "-home-natha-OverSteward" / "session" / "subagents" / "agent-a.jsonl"
    return _write(path, _before_the_answer())


def test_the_sweep_finds_a_held_subagent_under_the_projects_root(tmp_path):
    held = _held_tree(tmp_path)
    _write(tmp_path / "p" / "s" / "subagents" / "agent-b.jsonl", _entries())
    now = datetime.fromtimestamp(held.stat().st_mtime, UTC) + timedelta(minutes=30)

    found = dispatch_run.recent_transcripts(tmp_path, now, window_hours=24)
    result = dispatch_run.sweep(found, now, warn_min=10)

    assert result.checked == 2
    assert [p.transcript for p in result.blocked] == [str(held)]


def test_the_sweep_window_skips_a_transcript_written_long_ago(tmp_path):
    held = _held_tree(tmp_path)
    old = held.stat().st_mtime - 48 * 3600
    os.utime(held, (old, old))

    assert dispatch_run.recent_transcripts(tmp_path, datetime.now(UTC), window_hours=24) == []


def test_the_cli_alerts_with_exit_3_and_names_the_transcript(tmp_path, capsys):
    held = _held_tree(tmp_path)

    rc = cli.main(["prompts", "--root", str(tmp_path), "--warn-min", "10"])

    out = capsys.readouterr().out
    assert rc == 3
    assert f"BLOCKED {held}: tool call {HELD_ID}" in out
    assert "1 held prompt(s) across 1 transcript(s) checked" in out


def test_a_session_watch_ignores_another_sessions_held_agent(tmp_path, capsys):
    """Only the other session's subagent is held; this session's is clear."""
    other = _held_tree(tmp_path)
    _write(tmp_path / "-home-natha-OverSteward" / "mine" / "subagents" / "agent-b.jsonl", _entries())

    scoped = cli.main(["prompts", "--root", str(tmp_path), "--session", "mine"])
    scoped_out = capsys.readouterr().out
    unscoped = cli.main(["prompts", "--root", str(tmp_path)])

    assert scoped == 0
    assert "0 held prompt(s) across 1 transcript(s) checked" in scoped_out
    assert str(other) not in scoped_out
    assert unscoped == 3


@pytest.mark.parametrize("session", ["..", "a/b", "*", ""])
def test_a_session_that_is_not_an_id_could_not_look(tmp_path, capsys, session):
    _held_tree(tmp_path)

    rc = cli.main(["prompts", "--root", str(tmp_path), "--session", session])

    out = capsys.readouterr().out
    assert rc == 2
    assert "is not a session id" in out
    assert "Traceback" not in out


def test_the_cli_is_clear_with_exit_0_and_counts_what_it_read(tmp_path, capsys):
    _write(tmp_path / "p" / "s" / "subagents" / "agent-b.jsonl", _entries())

    rc = cli.main(["prompts", "--root", str(tmp_path)])

    assert rc == 0
    assert "0 held prompt(s) across 1 transcript(s) checked" in capsys.readouterr().out


def test_the_cli_says_it_could_not_look_when_there_is_nothing(tmp_path, capsys):
    rc = cli.main(["prompts", "--root", str(tmp_path)])

    assert rc == 2
    assert "nothing to look at" in capsys.readouterr().out


def test_the_cli_reports_an_unreadable_transcript_as_exit_1(tmp_path, capsys):
    path = tmp_path / "p" / "s" / "subagents" / "agent-c.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('not json\n{"type": "user"}\n', encoding="utf-8")

    rc = cli.main(["prompts", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "could not read a transcript" in out
    assert "Traceback" not in out


def test_watch_returns_as_soon_as_a_prompt_is_held(tmp_path):
    """Clear at first; the transcript then gains the ask, and the next sweep past the warning ends it."""
    path = _write(tmp_path / "t.jsonl", _before_the_answer()[:-1])
    clock_times = iter(ASKED_AT + timedelta(minutes=m) for m in range(0, 600, 5))
    sleeps: list[float] = []

    def find(now):
        if now >= ASKED_AT + timedelta(minutes=5):
            _write(path, _before_the_answer())
        return [path]

    result = dispatch_run.watch(
        find, warn_min=10, for_min=480, poll_sec=300,
        clock=lambda: next(clock_times), sleeper=sleeps.append,
    )

    assert [p.tool_use_id for p in result.blocked] == [HELD_ID]
    # swept at +5 (5m old: under the warning, sleep) and +10 (alert, return)
    assert len(sleeps) == 1


def test_watch_gives_up_clear_after_for_min(tmp_path):
    clear = _write(tmp_path / "t.jsonl", _entries())
    clock_times = iter(ASKED_AT + timedelta(minutes=m) for m in range(0, 600, 5))
    sleeps: list[float] = []

    result = dispatch_run.watch(
        lambda now: [clear], warn_min=10, for_min=30, poll_sec=300,
        clock=lambda: next(clock_times), sleeper=sleeps.append,
    )

    assert result.blocked == ()
    assert result.checked == 1
    # swept at +5 .. +30; the sweep at +30 reaches for_min and returns without sleeping
    assert len(sleeps) == 5


# --- the measured duration -------------------------------------------------


def _ag2736_report() -> str:
    handback = _entries()[-2]["message"]["content"][0]["input"]["message"]
    return handback


def test_the_ag2736_report_is_not_a_measurement():
    """The real report: 9000 seconds, no stamps, against a span of about 27,060."""
    report = dispatch_run.report_from_text(_ag2736_report())
    span = dispatch_run.transcript_span_s(_entries())

    problems = dispatch_run.duration_problems(report, span)

    assert report["duration_seconds"] == 9000
    assert round(span) == 27059
    assert any(p.startswith("started_at is missing") for p in problems)
    assert any(p.startswith("ended_at is missing") for p in problems)
    assert any("disagrees with the transcript's span of 27059s" in p for p in problems)


def _stamped(duration: int, started: str = "2026-11-07T03:05:52Z", ended: str = "2026-11-07T10:36:40Z"):
    return {"duration_seconds": duration, "started_at": started, "ended_at": ended}


def test_a_duration_computed_from_its_stamps_is_measured():
    assert dispatch_run.duration_problems(_stamped(27048)) == []


def test_an_estimated_duration_beside_true_stamps_fails():
    problems = dispatch_run.duration_problems(_stamped(9000))

    assert problems == ["duration_seconds 9000 != ended_at - started_at = 27048"]


@pytest.mark.parametrize("off_by", [-2, 2])
def test_a_duration_two_seconds_off_its_stamps_fails(off_by):
    assert dispatch_run.duration_problems(_stamped(27048 + off_by)) != []


def test_stamps_written_to_fit_an_estimate_fail_against_the_transcript():
    """started/ended chosen so the arithmetic agrees with 9000 — the span still does not."""
    report = _stamped(9000, "2026-11-07T08:06:40Z", "2026-11-07T10:36:40Z")
    span = dispatch_run.transcript_span_s(_entries())

    problems = dispatch_run.duration_problems(report, span)

    assert problems == [
        "duration_seconds 9000 disagrees with the transcript's span of 27059s (tolerance 300s)"
    ]


@pytest.mark.parametrize("delta", [-300, 300])
def test_the_span_tolerance_is_inclusive(delta):
    span = 27059.0
    duration = int(span) + delta
    started = datetime(2026, 11, 7, 3, 5, 52, tzinfo=UTC)
    ended = started + timedelta(seconds=duration)
    report = _stamped(duration, f"{started:%Y-%m-%dT%H:%M:%SZ}", f"{ended:%Y-%m-%dT%H:%M:%SZ}")

    assert dispatch_run.duration_problems(report, span) == []


def test_a_span_just_past_the_tolerance_fails():
    started = datetime(2026, 11, 7, 3, 5, 52, tzinfo=UTC)
    ended = started + timedelta(seconds=27059 + 301)
    report = _stamped(27059 + 301, f"{started:%Y-%m-%dT%H:%M:%SZ}", f"{ended:%Y-%m-%dT%H:%M:%SZ}")

    assert dispatch_run.duration_problems(report, 27059.0) != []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("started_at", "2026-11-07T03:05:52", "is not an ISO-8601 UTC stamp"),
        ("ended_at", "yesterday", "is not an ISO-8601 UTC stamp"),
        ("duration_seconds", "27048", "is not an integer"),
        ("duration_seconds", True, "is not an integer"),
    ],
)
def test_a_malformed_field_is_named(field, value, expected):
    report = _stamped(27048)
    report[field] = value

    assert any(expected in p for p in dispatch_run.duration_problems(report))


def test_an_end_before_the_start_fails():
    report = _stamped(-60, "2026-11-07T10:36:40Z", "2026-11-07T10:35:40Z")

    assert any("is before started_at" in p for p in dispatch_run.duration_problems(report))


def test_yaml_parses_unquoted_stamps_and_they_still_measure():
    text = (
        "Done.\n\n```yaml\nfinal_state: MERGED\nduration_seconds: 27048\n"
        "started_at: 2026-11-07T03:05:52Z\nended_at: 2026-11-07T10:36:40Z\n```\n"
    )

    assert dispatch_run.duration_problems(dispatch_run.report_from_text(text)) == []


def test_the_cli_fails_the_ag2736_report_with_exit_1(tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text(_ag2736_report(), encoding="utf-8")

    rc = cli.main(["report", str(report), "--transcript", str(FIXTURE)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT MEASURED: started_at is missing" in out


def test_the_cli_checks_fitted_stamps_against_the_transcript(tmp_path, capsys):
    """The stamps agree with 9000; only the transcript's span shows the estimate."""
    report = tmp_path / "report.md"
    report.write_text(
        "```yaml\nduration_seconds: 9000\nstarted_at: 2026-11-07T08:06:40Z\n"
        "ended_at: 2026-11-07T10:36:40Z\n```\n",
        encoding="utf-8",
    )

    rc = cli.main(["report", str(report), "--transcript", str(FIXTURE)])

    assert rc == 1
    assert "disagrees with the transcript's span of 27059s" in capsys.readouterr().out


def test_the_cli_passes_a_measured_report_with_exit_0(tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text(
        "```yaml\nduration_seconds: 27048\nstarted_at: 2026-11-07T03:05:52Z\n"
        "ended_at: 2026-11-07T10:36:40Z\n```\n",
        encoding="utf-8",
    )

    rc = cli.main(["report", str(report), "--transcript", str(FIXTURE)])

    assert rc == 0
    assert "measured: duration_seconds 27048" in capsys.readouterr().out


def test_the_cli_could_not_read_a_report_without_yaml(tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text("All done, merged.", encoding="utf-8")

    rc = cli.main(["report", str(report)])

    out = capsys.readouterr().out
    assert rc == 2
    assert "could not read" in out


# --- the real capture --------------------------------------------------------


@pytest.mark.skipif(not REAL_CAPTURE.exists(), reason="the AG#2736 capture is not on this machine")
def test_the_real_ag2736_capture_alerts_mid_hold_and_fails_its_report():
    entries = dispatch_run.read_entries(REAL_CAPTURE)
    cut = next(i for i, e in enumerate(entries) if str(e.get("timestamp", "")) >= "2026-11-07T10:36")
    now = datetime(2026, 11, 7, 10, 30, tzinfo=UTC)

    held = dispatch_run.blocked_prompts(entries[:cut], now, warn_min=10)
    report = dispatch_run.report_from_text(
        next(
            block["input"]["message"]
            for e in entries
            for block in (e.get("message") or {}).get("content") or []
            if isinstance(block, dict) and block.get("name") == "SubagentHandback"
        )
    )

    assert [p.tool_use_id for p in held] == [HELD_ID]
    assert dispatch_run.pending_prompts(entries) == []
    assert dispatch_run.duration_problems(report, dispatch_run.transcript_span_s(entries)) != []
