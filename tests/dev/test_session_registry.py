# ABOUTME: Tests the canonical session registry (shared/scripts/dev/session_registry.py).
# ABOUTME: Name precedence, retire-keeps-the-row, crash-reads-as-live, and the tmux resume plan.

"""OS#486: hooks that write the live sessions down, and a boot verb that reopens them.

Every assertion here is about a way the registry could quietly do nothing: a
name that never improves past the cwd basename, a retire that loses the row it
was meant to annotate, a crashed session that reads as cleanly ended (and so is
never resumed), and a `resume` on a machine with no tmux that exits like a
success. Each of those failure modes is silent in production — the file simply
looks plausible — so each gets a negative fixture here.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.dev.conftest import CANONICAL_DEV, load_dev_script

SCRIPT = "session_registry.py"
SCRIPT_PATH = CANONICAL_DEV / SCRIPT
DEPLOYED_PATH = CANONICAL_DEV.parents[2] / "scripts" / "dev" / SCRIPT

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_COULD_NOT_LOOK = 2

T0 = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
SESSION = "2330625f-5916-4796-94e6-c404b8a8385f"
OTHER_SESSION = "13d4e2f1-2f8c-4c24-ba68-e62425a51c05"

# A tmux stand-in: reports "no such session" so the plan starts with new-session,
# and logs every invocation so a test can prove the verb acted rather than printed.
TMUX_STUB = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("TMUX_STUB_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(1 if sys.argv[1:2] == ["has-session"] else 0)
"""


@pytest.fixture(scope="module")
def registry():
    return load_dev_script(SCRIPT)


@pytest.fixture
def tmux_stub(tmp_path) -> Path:
    stub = tmp_path / "tmux-stub"
    stub.write_text(TMUX_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def transcript(*titles: str) -> str:
    """A transcript tail carrying `ai-title` records among unrelated ones."""
    lines = [json.dumps({"type": "queue-operation", "operation": "enqueue"})]
    for title in titles:
        lines.append(json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": SESSION}))
    lines.append(json.dumps({"type": "atis-latch", "atis": ""}))
    return "\n".join(lines) + "\n"


def payload(**overrides) -> dict:
    """A SessionStart payload in the shape Claude Code 2.1.258 actually emits."""
    base = {
        "session_id": SESSION,
        "transcript_path": "/home/natha/.claude/projects/-home-natha-OverSteward/x.jsonl",
        "cwd": "/home/natha/OverSteward",
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    base.update(overrides)
    return base


def reader(text: str):
    """The transcript-reading seam, injected — never a patched module global."""
    return lambda _path: text


def run_cli(*args: str, stdin: str = "", env_extra: dict[str, str] | None = None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class TestNameResolution:
    """Nathan will not name sessions by hand, so the fallbacks carry the feature."""

    def test_an_explicit_name_wins_over_the_transcript_title(self, registry):
        name, source = registry.resolve_name(
            payload(session_title="td-numbers"), reader(transcript("Excessive usage problem"))
        )
        assert (name, source) == ("td-numbers", registry.EXPLICIT)

    def test_the_latest_ai_title_is_used_when_no_name_was_given(self, registry):
        name, source = registry.resolve_name(
            payload(), reader(transcript("First guess", "Excessive usage problem"))
        )
        assert (name, source) == ("Excessive usage problem", registry.AI_TITLE)

    def test_the_cwd_basename_is_the_last_resort(self, registry):
        name, source = registry.resolve_name(payload(), reader(transcript()))
        assert (name, source) == ("OverSteward", registry.CWD_BASENAME)

    def test_a_blank_explicit_name_does_not_shadow_the_transcript_title(self, registry):
        name, source = registry.resolve_name(
            payload(session_title="   "), reader(transcript("Excessive usage problem"))
        )
        assert (name, source) == ("Excessive usage problem", registry.AI_TITLE)


class TestNameNeverDemotes:
    """A fresh session has no ai-title yet; the next hook must be able to improve it."""

    def test_a_cwd_fallback_is_upgraded_once_a_title_exists(self, registry):
        first = registry.record_row(payload(), None, T0, reader(transcript()))
        assert first["name_source"] == registry.CWD_BASENAME

        second = registry.record_row(
            payload(source="resume"), first, T0 + timedelta(hours=1), reader(transcript("Session registry"))
        )
        assert (second["name"], second["name_source"]) == ("Session registry", registry.AI_TITLE)

    def test_an_explicit_name_survives_a_later_transcript_title(self, registry):
        first = registry.record_row(
            payload(session_title="td-numbers"), None, T0, reader(transcript())
        )
        second = registry.record_row(
            payload(), first, T0 + timedelta(hours=1), reader(transcript("Something else"))
        )
        assert (second["name"], second["name_source"]) == ("td-numbers", registry.EXPLICIT)


class TestRetireKeepsTheRow:
    def test_retire_annotates_the_row_rather_than_replacing_it(self, registry):
        started = registry.record_row(payload(), None, T0, reader(transcript("Session registry")))
        ended = registry.retire_row(
            {"session_id": SESSION, "hook_event_name": "SessionEnd", "reason": "other"},
            started,
            T0 + timedelta(hours=2),
            reader(transcript("Session registry")),
        )
        assert ended["session_id"] == started["session_id"]
        assert ended["started_at"] == started["started_at"]
        assert ended["cwd"] == started["cwd"]
        assert ended["name"] == started["name"]
        assert ended["ended_at"] == (T0 + timedelta(hours=2)).isoformat()
        assert ended["end_reason"] == "other"

    def test_a_recorded_row_carries_no_end_marker(self, registry):
        assert registry.record_row(payload(), None, T0, reader(transcript()))["ended_at"] is None


class TestLiveness:
    """A crash never runs SessionEnd — that absence IS the liveness signal."""

    def _folded(self, registry, *rows):
        return registry.fold_rows(json.dumps(row) for row in rows)

    def crashed(self, registry):
        return registry.record_row(payload(), None, T0, reader(transcript("Crashed session")))

    def ended(self, registry):
        started = registry.record_row(
            payload(session_id=OTHER_SESSION), None, T0, reader(transcript())
        )
        return registry.retire_row(
            {"session_id": OTHER_SESSION, "reason": "clear"},
            started,
            T0 + timedelta(minutes=5),
            reader(transcript()),
        )

    def test_a_session_with_no_session_end_is_live(self, registry):
        folded = self._folded(registry, self.crashed(registry))
        live = registry.live_rows(folded, T0 + timedelta(hours=1), 24)
        assert [row["session_id"] for row in live] == [SESSION]

    def test_a_cleanly_ended_session_is_not_live(self, registry):
        folded = self._folded(registry, self.crashed(registry), self.ended(registry))
        live = registry.live_rows(folded, T0 + timedelta(hours=1), 24)
        assert [row["session_id"] for row in live] == [SESSION]

    def test_include_ended_brings_the_retired_row_back(self, registry):
        folded = self._folded(registry, self.crashed(registry), self.ended(registry))
        live = registry.live_rows(folded, T0 + timedelta(hours=1), 24, include_ended=True)
        assert {row["session_id"] for row in live} == {SESSION, OTHER_SESSION}

    def test_a_row_older_than_the_window_is_dropped(self, registry):
        folded = self._folded(registry, self.crashed(registry))
        assert registry.live_rows(folded, T0 + timedelta(hours=30), 24) == []

    def test_no_window_keeps_the_old_row(self, registry):
        folded = self._folded(registry, self.crashed(registry))
        assert len(registry.live_rows(folded, T0 + timedelta(hours=30), None)) == 1

    def test_the_log_folds_last_write_wins(self, registry):
        started = self.crashed(registry)
        ended = registry.retire_row(
            {"session_id": SESSION, "reason": "clear"},
            started,
            T0 + timedelta(minutes=1),
            reader(transcript()),
        )
        folded = self._folded(registry, started, ended)
        assert len(folded.rows) == 1
        assert folded.rows[SESSION]["ended_at"] is not None

    def test_an_unparseable_line_is_counted_not_swallowed(self, registry):
        folded = registry.fold_rows(["{not json}", json.dumps(self.crashed(registry))])
        assert (len(folded.rows), folded.unreadable) == (1, 1)


class TestWindowPlan:
    def test_one_window_per_row_resuming_that_row_in_its_own_cwd(self, registry):
        rows = [
            {"session_id": SESSION, "name": "Session registry", "cwd": "/home/natha/OverSteward"},
            {"session_id": OTHER_SESSION, "name": "td numbers", "cwd": "/home/natha/grantspider"},
        ]
        windows = registry.plan_windows(rows)
        assert [window.cwd for window in windows] == [
            "/home/natha/OverSteward",
            "/home/natha/grantspider",
        ]
        assert windows[0].command.endswith(f"-r {SESSION}")
        assert windows[1].command.endswith(f"-r {OTHER_SESSION}")

    def test_window_names_are_tmux_safe(self, registry):
        assert registry.window_name("Excessive usage problem") == "Excessive-usage-problem"
        assert registry.window_name("fix: a.b:c") == "fix-a-b-c"
        assert registry.window_name("...") == "session"

    def test_the_first_window_creates_the_tmux_session_when_there_is_none(self, registry):
        windows = registry.plan_windows([{"session_id": SESSION, "name": "a", "cwd": "/tmp"}])
        commands = registry.tmux_commands(windows, "tmux", "claude", session_exists=False)
        assert commands[0][:2] == ["tmux", "new-session"]

    def test_an_existing_tmux_session_gets_windows_added_not_recreated(self, registry):
        windows = registry.plan_windows([{"session_id": SESSION, "name": "a", "cwd": "/tmp"}])
        commands = registry.tmux_commands(windows, "tmux", "claude", session_exists=True)
        assert commands[0][:2] == ["tmux", "new-window"]


class TestCommandLine:
    """End to end through the hook payloads Claude Code really emits."""

    def _record(self, store: Path, transcript_path: Path, **overrides):
        return run_cli(
            "record",
            "--registry",
            str(store),
            "--transcript-root",
            str(transcript_path.parent),
            stdin=json.dumps(payload(transcript_path=str(transcript_path), **overrides)),
        )

    def test_record_then_list_reports_the_transcript_title(self, tmp_path):
        store = tmp_path / "session-registry.jsonl"
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")

        assert self._record(store, note).returncode == EXIT_OK
        listed = run_cli("list", "--registry", str(store))
        assert listed.returncode == EXIT_OK
        assert "Session registry" in listed.stdout
        assert SESSION in listed.stdout
        assert "1 live of 1 recorded" in listed.stdout

    def test_a_retired_session_drops_out_of_list(self, tmp_path):
        store = tmp_path / "session-registry.jsonl"
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")
        self._record(store, note)
        retired = run_cli(
            "retire",
            "--registry",
            str(store),
            "--transcript-root",
            str(note.parent),
            stdin=json.dumps({"session_id": SESSION, "reason": "clear"}),
        )
        assert retired.returncode == EXIT_OK

        listed = run_cli("list", "--registry", str(store))
        assert "0 live of 1 recorded" in listed.stdout

    def test_a_payload_without_a_session_id_is_refused(self, tmp_path):
        store = tmp_path / "session-registry.jsonl"
        result = run_cli("record", "--registry", str(store), stdin=json.dumps({"cwd": "/tmp"}))
        assert result.returncode == EXIT_FAILED
        assert not store.exists()

    def test_resume_dry_run_plans_one_window_per_live_session(self, tmp_path, tmux_stub):
        store = tmp_path / "session-registry.jsonl"
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")
        self._record(store, note)
        self._record(store, note, session_id=OTHER_SESSION, cwd="/home/natha/grantspider")

        result = run_cli(
            "resume",
            "--dry-run",
            "--registry",
            str(store),
            "--tmux-bin",
            str(tmux_stub),
        )
        assert result.returncode == EXIT_OK
        planned = [line for line in result.stdout.splitlines() if str(tmux_stub) in line]
        assert len(planned) == 2
        assert any("/home/natha/OverSteward" in line and SESSION in line for line in planned)
        assert any("/home/natha/grantspider" in line and OTHER_SESSION in line for line in planned)
        assert "would open 2 window(s)" in result.stdout

    def test_resume_dry_run_opens_nothing(self, tmp_path, tmux_stub):
        store = tmp_path / "session-registry.jsonl"
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")
        self._record(store, note)
        log = tmp_path / "tmux.log"

        run_cli(
            "resume", "--dry-run", "--registry", str(store), "--tmux-bin", str(tmux_stub),
            env_extra={"TMUX_STUB_LOG": str(log)},
        )
        assert "new-session" not in (log.read_text(encoding="utf-8") if log.exists() else "")

    def test_resume_actually_opens_the_windows(self, tmp_path, tmux_stub):
        store = tmp_path / "session-registry.jsonl"
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")
        self._record(store, note)
        log = tmp_path / "tmux.log"

        result = run_cli(
            "resume", "--registry", str(store), "--tmux-bin", str(tmux_stub),
            env_extra={"TMUX_STUB_LOG": str(log)},
        )
        assert result.returncode == EXIT_OK
        opened = log.read_text(encoding="utf-8")
        assert "new-session" in opened
        assert f"-r {SESSION}" in opened
        assert "opened 1 window(s)" in result.stdout


class TestTranscriptRoot:
    """The payload names the transcript; a hook must not open whatever it is handed."""

    def test_a_transcript_under_the_root_is_read(self, tmp_path, registry):
        note = tmp_path / "x.jsonl"
        note.write_text(transcript("Session registry"), encoding="utf-8")
        read = registry.transcript_reader(tmp_path)
        assert registry.latest_ai_title(read(str(note))) == "Session registry"

    def test_a_transcript_outside_the_root_is_refused_and_named(self, tmp_path, registry, capsys):
        outside = tmp_path / "outside" / "secrets.jsonl"
        outside.parent.mkdir()
        outside.write_text(transcript("Should not be read"), encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()

        assert registry.transcript_reader(root)(str(outside)) == ""
        assert "refusing a transcript outside" in capsys.readouterr().err

    def test_a_refused_transcript_falls_back_to_the_cwd_basename(self, tmp_path, registry):
        outside = tmp_path / "x.jsonl"
        outside.write_text(transcript("Should not be read"), encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()

        name, source = registry.resolve_name(
            payload(transcript_path=str(outside)), registry.transcript_reader(root)
        )
        assert (name, source) == ("OverSteward", registry.CWD_BASENAME)


class TestSkipIsNotAPass:
    """A blind run and a quiet one must not share an exit code."""

    def test_resume_without_tmux_exits_two(self, tmp_path):
        store = tmp_path / "session-registry.jsonl"
        store.write_text("", encoding="utf-8")
        result = run_cli("resume", "--registry", str(store), env_extra={"PATH": ""})
        assert result.returncode == EXIT_COULD_NOT_LOOK
        assert "tmux" in result.stderr

    def test_resume_without_a_registry_exits_two(self, tmp_path, tmux_stub):
        result = run_cli(
            "resume", "--registry", str(tmp_path / "absent.jsonl"), "--tmux-bin", str(tmux_stub)
        )
        assert result.returncode == EXIT_COULD_NOT_LOOK

    def test_list_without_a_registry_exits_two(self, tmp_path):
        result = run_cli("list", "--registry", str(tmp_path / "absent.jsonl"))
        assert result.returncode == EXIT_COULD_NOT_LOOK
        assert "COULD NOT LOOK" in result.stderr

    def test_an_empty_registry_is_a_measured_zero(self, tmp_path):
        store = tmp_path / "session-registry.jsonl"
        store.write_text("", encoding="utf-8")
        result = run_cli("list", "--registry", str(store))
        assert result.returncode == EXIT_OK
        assert "0 live of 0 recorded" in result.stdout


def test_canonical_and_deployed_copies_are_byte_identical():
    """A one-sided edit to a canonical byte-copy is the drift bug this family keeps hitting."""
    assert SCRIPT_PATH.read_bytes() == DEPLOYED_PATH.read_bytes(), (
        f"{SCRIPT} drifted between shared/scripts/dev/ and scripts/dev/. "
        "Edit the canonical copy and byte-copy it across; never dual-edit."
    )
