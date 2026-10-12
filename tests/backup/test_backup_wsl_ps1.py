# ABOUTME: Tests for ops/wsl/Backup-Wsl.ps1 and its installer — the export is gated, never forced.
# ABOUTME: Text checks always run; behaviour runs under Windows PowerShell with wsl.exe faked.

"""Backup-Wsl.ps1 must never run ``wsl --export`` unless the readiness check said 0.

Two layers. The text checks read the scripts and hold on any box, CI included.
The behaviour checks run the real script under ``powershell.exe`` (reachable from
WSL through interop) with ``wsl.exe`` shadowed by a PowerShell function, so the
script's own control flow is exercised and nothing ever reaches the real
``wsl.exe`` — a gate bug in a test must not be able to stop the distro the test
is running in. Off WSL, the behaviour checks skip and say so.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP = REPO_ROOT / "ops" / "wsl" / "Backup-Wsl.ps1"
INSTALLER = REPO_ROOT / "ops" / "wsl" / "Install-WslResilience.ps1"
README = REPO_ROOT / "ops" / "wsl" / "README.md"
RUNBOOK = REPO_ROOT / "documentation" / "runbooks" / "wsl-recovery.md"

PRIMARY_PYTHON = "/home/natha/OverSteward/.venv/bin/python"
PRIMARY_READINESS = "/home/natha/OverSteward/scripts/backup_ready.py"


def _code(path: Path) -> str:
    """Script text with comment-only lines and <# ... #> help blocks removed."""
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


# --- text checks: always run ------------------------------------------------


class TestBackupScriptText:
    def test_readiness_runs_before_the_export(self):
        code = _code(BACKUP)
        assert "backup_ready.py" in code
        assert "--export" in code
        gate = code.index("-- $ReadinessPython $ReadinessScript")
        assert gate < code.index("wsl.exe --export $Distro")

    def test_readiness_targets_the_primary_checkout_never_a_worktree(self):
        code = _code(BACKUP)
        assert f"'{PRIMARY_PYTHON}'" in code
        assert f"'{PRIMARY_READINESS}'" in code
        assert ".claude/worktrees" not in BACKUP.read_text(encoding="utf-8")

    def test_keep_defaults_to_one(self):
        assert re.search(r"\[int\]\$Keep\s*=\s*1\b", _code(BACKUP))

    def test_a_skip_exits_three(self):
        assert re.search(r"\bexit\s+3\b", _code(BACKUP))

    def test_writes_the_last_ok_marker(self):
        assert "export.last-ok" in _code(BACKUP)

    def test_due_and_overdue_thresholds_are_28_and_35_days(self):
        code = _code(BACKUP)
        assert re.search(r"\[int\]\$DueDays\s*=\s*28\b", code)
        assert re.search(r"\[int\]\$OverdueDays\s*=\s*35\b", code)


class TestInstallerText:
    def test_schedules_a_daily_trigger_not_a_monthly_one(self):
        # MSFT_TaskMonthlyDOWTrigger failed Register-ScheduledTask with 0x80070057
        # on the live scheduler (2026-10-11); the script decides due-ness instead.
        code = _code(INSTALLER)
        assert re.search(r"New-ScheduledTaskTrigger\s+-Daily\s+-At\s+\$DailyTime", code)
        assert "MSFT_TaskMonthlyDOWTrigger" not in code
        assert "MonthOfYear" not in code

    def test_starts_at_0117_and_retries_hourly_for_five_hours(self):
        code = _code(INSTALLER)
        assert re.search(r"\[string\]\$DailyTime\s*=\s*'01:17'", code)
        assert re.search(
            r"New-ScheduledTaskTrigger\s+-Once\s+-At\s+\$DailyTime\s+"
            r"-RepetitionInterval\s+\(New-TimeSpan\s+-Hours\s+1\)\s+"
            r"-RepetitionDuration\s+\(New-TimeSpan\s+-Hours\s+5\)\)\.Repetition",
            code,
        )
        assert re.search(r"\$backupTrigger\.Repetition\s*=", code)

    def test_a_running_export_is_not_stopped_when_the_retry_window_ends(self):
        # The borrowed -Once repetition carries StopAtDurationEnd=True, which would
        # kill an export started late in the window when the window closes.
        assert re.search(r"\$backupTrigger\.Repetition\.StopAtDurationEnd\s*=\s*\$false", _code(INSTALLER))

    def test_no_weekly_trigger_remains(self):
        assert "-Weekly" not in _code(INSTALLER)

    def test_removes_the_weekly_task_it_replaces(self):
        assert re.search(r"Unregister-ScheduledTask\s+-TaskName\s+'WSL Weekly Backup'\s+-Confirm:\$false",
                         _code(INSTALLER))


class TestDocsText:
    @pytest.mark.parametrize("doc", [README, RUNBOOK], ids=["readme", "runbook"])
    @pytest.mark.parametrize(
        "phrase",
        ["weekly", "03:17", "stops the distro", "first sunday", "05:17", "17 hours"],
    )
    def test_no_weekly_or_distro_stopping_prescription(self, doc, phrase):
        text = doc.read_text(encoding="utf-8").lower()
        # The installer's cleanup of the retired task is the one sanctioned mention.
        text = text.replace("'wsl weekly backup'", "")
        assert phrase not in text


# --- behaviour checks: Windows PowerShell with wsl.exe faked ----------------

_POWERSHELL = shutil.which("powershell.exe")
_WSLPATH = shutil.which("wslpath")

windows = pytest.mark.skipif(
    _POWERSHELL is None or _WSLPATH is None,
    reason="needs powershell.exe and wslpath (WSL interop) to run the script",
)


def _win(path: Path) -> str:
    return subprocess.run(
        [_WSLPATH, "-w", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()


_EXPORT_OK = (
    "Set-Content -LiteralPath $args[-1] -Value 'archive' -Encoding ASCII; "
    "$global:LASTEXITCODE = 0"
)

_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:WslCalls = New-Object System.Collections.ArrayList
function __FAKENAME__ {
    [void]$global:WslCalls.Add(($args -join ' '))
    if ($args -contains '--export') {
        __EXPORT__
        return
    }
    __READINESS__
}
$global:Alerts = New-Object System.Collections.ArrayList
function Start-Process {
    param($FilePath, $ArgumentList, $WindowStyle)
    $encoded = $ArgumentList[[array]::IndexOf($ArgumentList, '-EncodedCommand') + 1]
    $command = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
    # Parse, never run, the dialog command: a quoting slip would fail silently on the box.
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($command, [ref]$null, [ref]$errors)
    $flat = ("PARSE-ERRORS:$($errors.Count) $FilePath " + $command) -replace "`r?`n", ' | '
    [void]$global:Alerts.Add($flat)
}
function Set-LastOk([int]$daysAgo) {
    Set-Content -LiteralPath (Join-Path '__STATE__' 'export.last-ok') `
        -Value (Get-Date).Date.AddDays(-$daysAgo).ToString('yyyy-MM-dd')
}
__PRELUDE__
$code = 0
try {
    & '__SCRIPT__' -Distro 'Fake-Distro' -Dest '__DEST__' -StateDir '__STATE__' __EXTRA__
    $code = $LASTEXITCODE
} catch {
    Write-Output "THREW: $_"
    $code = 99
}
foreach ($c in $global:WslCalls) { Write-Output "WSLCALL: $c" }
foreach ($a in $global:Alerts) { Write-Output "ALERT: $a" }
exit $code
"""


def _readiness(code: int, line: str) -> str:
    return f"Write-Output '{line}'; $global:LASTEXITCODE = {code}"


def _run_backup(
    tmp_path: Path,
    readiness: str,
    prelude: str = "",
    extra: str = "",
    distro: str = "Fake-Distro",
    real_wsl: bool = False,
    export: str = _EXPORT_OK,
):
    dest = tmp_path / "dest"
    state = tmp_path / "state"
    dest.mkdir()
    state.mkdir()
    harness = (
        _HARNESS.replace("__FAKENAME__", "unused-fake" if real_wsl else "wsl.exe")
        .replace("'Fake-Distro'", f"'{distro}'")
        .replace("__READINESS__", readiness)
        .replace("__EXPORT__", export)
        .replace("__PRELUDE__", prelude)
        .replace("__SCRIPT__", _win(BACKUP))
        .replace("__DEST__", _win(dest))
        .replace("__STATE__", _win(state))
        .replace("__EXTRA__", extra)
    )
    wrapper = tmp_path / "harness.ps1"
    wrapper.write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _win(wrapper)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    calls = [
        line.removeprefix("WSLCALL: ").strip()
        for line in proc.stdout.splitlines()
        if line.startswith("WSLCALL: ")
    ]
    log = state / "backup.log"
    return proc, calls, dest, state, (log.read_text(encoding="utf-8") if log.exists() else "")


def _alerts(proc) -> list[str]:
    return [
        line.removeprefix("ALERT: ").strip()
        for line in proc.stdout.splitlines()
        if line.startswith("ALERT: ")
    ]


def _exports(calls: list[str]) -> list[str]:
    return [c for c in calls if "--export" in c]


@windows
class TestBackupScriptBehaviour:
    def test_ready_exports_after_the_readiness_call_and_marks_today(self, tmp_path):
        proc, calls, dest, state, log = _run_backup(
            tmp_path, _readiness(0, "READY - 3 probes clean")
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        # PowerShell consumes "--" at a function boundary, so the fake never sees
        # it; the native wsl.exe does, and the text check above pins it.
        assert calls[0] == f"-d Fake-Distro {PRIMARY_PYTHON} {PRIMARY_READINESS}"
        assert len(_exports(calls)) == 1
        assert calls.index(_exports(calls)[0]) > 0
        assert list(dest.glob("Fake-Distro_*.tar"))
        marker = (state / "export.last-ok").read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", marker)
        assert "OK" in log

    @pytest.mark.parametrize(
        ("code", "line"),
        [(1, "BUSY - pid 1422 claude --resume"), (2, "COULD NOT LOOK - docker: not found")],
        ids=["busy", "could-not-look"],
    )
    def test_not_ready_skips_with_exit_three_and_logs_the_blocker(self, tmp_path, code, line):
        proc, calls, dest, state, log = _run_backup(tmp_path, _readiness(code, line))
        label = "busy" if code == 1 else "could not look"
        assert f"SKIPPED - {label} (" in log
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert not list(dest.iterdir())
        assert not (state / "export.last-ok").exists()
        assert line in log
        assert f"readiness exit {code}" in log

    def test_exit_one_without_a_busy_verdict_is_could_not_look(self, tmp_path):
        # A Python traceback also exits 1; only a BUSY headline is a busy verdict.
        proc, calls, _dest, _state, log = _run_backup(
            tmp_path,
            _readiness(1, "ModuleNotFoundError: No module named oversteward.backup"),
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert "SKIPPED - could not look (readiness exit 1)" in log

    def test_the_readiness_paths_can_be_overridden(self, tmp_path):
        proc, calls, _dest, _state, _log = _run_backup(
            tmp_path,
            _readiness(1, "BUSY - pid 9 claude"),
            extra="-ReadinessPython '/opt/py' -ReadinessScript '/opt/ready.py'",
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert calls[0] == "-d Fake-Distro /opt/py /opt/ready.py"

    @pytest.mark.parametrize(
        "export",
        [
            # A partial archive, then failure: the file exists and is not empty.
            "Set-Content -LiteralPath $args[-1] -Value 'partial'; $global:LASTEXITCODE = 5",
            "Set-Content -LiteralPath $args[-1] -Value $null; $global:LASTEXITCODE = 0",
        ],
        ids=["export-exits-nonzero", "export-writes-zero-bytes"],
    )
    def test_a_failed_export_keeps_last_months_archive_and_writes_no_marker(
        self, tmp_path, export
    ):
        prelude = (
            "$old = Join-Path '__DEST__' 'Fake-Distro_2000-01-02.tar'; "
            "Set-Content -LiteralPath $old -Value 'old'; "
            "(Get-Item -LiteralPath $old).LastWriteTime = (Get-Date).AddDays(-40)"
        )
        proc, calls, dest, state, log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude, export=export
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
        assert "THREW:" in proc.stdout
        assert len(_exports(calls)) == 1
        assert [p.name for p in dest.iterdir()] == ["Fake-Distro_2000-01-02.tar"]
        assert not (state / "export.last-ok").exists()
        assert "FAILED" in log

    def test_a_failing_wsl_exe_is_could_not_look(self, tmp_path):
        proc, calls, dest, _state, log = _run_backup(
            tmp_path, "Write-Output 'WSL service unavailable'; $global:LASTEXITCODE = -1"
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert not list(dest.iterdir())
        assert "WSL service unavailable" in log

    def test_wsl_exe_that_cannot_be_started_is_could_not_look(self, tmp_path):
        proc, calls, dest, _state, log = _run_backup(
            tmp_path, "throw 'wsl.exe is not recognized'"
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert "wsl.exe is not recognized" in log

    def test_the_real_wsl_exe_failing_on_a_missing_distro_skips(self, tmp_path):
        # Real wsl.exe, no fake: a distro that does not exist cannot be exported
        # even if the gate were broken, so this run is safe on a live box.
        proc, _calls, dest, state, log = _run_backup(
            tmp_path, "", distro="OS581-No-Such-Distro", real_wsl=True
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert not list(dest.iterdir())
        assert not (state / "export.last-ok").exists()
        assert "could not look (wsl.exe failed)" in log
        # wsl.exe's own messages are UTF-16 unless told otherwise; the log must read.
        assert "\x00" not in log
        assert "There is no distribution" in log

    @pytest.mark.parametrize("days_ago", [0, 27], ids=["today", "27-days"])
    def test_a_recent_success_is_not_due_and_exits_zero_without_touching_wsl(
        self, tmp_path, days_ago
    ):
        proc, calls, dest, _state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=f"Set-LastOk {days_ago}"
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls == []
        assert not list(dest.iterdir())
        assert "not due" in proc.stdout.lower()
        assert _alerts(proc) == []

    @pytest.mark.parametrize("days_ago", [28, 40], ids=["28-days", "40-days"])
    def test_a_success_28_days_ago_or_older_is_due_and_exports(self, tmp_path, days_ago):
        proc, calls, _dest, state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=f"Set-LastOk {days_ago}"
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert len(_exports(calls)) == 1
        marker = (state / "export.last-ok").read_text(encoding="utf-8").strip()
        assert marker == _today(proc)

    def test_an_unreadable_marker_is_due(self, tmp_path):
        prelude = (
            "Set-Content -LiteralPath (Join-Path '__STATE__' 'export.last-ok') -Value 'garbage'"
        )
        proc, calls, _dest, _state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert len(_exports(calls)) == 1

    def test_a_marker_from_an_earlier_day_does_not_stop_the_export(self, tmp_path):
        prelude = (
            "Set-Content -LiteralPath (Join-Path '__STATE__' 'export.last-ok') "
            "-Value '2000-01-02'"
        )
        proc, calls, _dest, _state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert len(_exports(calls)) == 1

    def test_keep_one_prunes_the_previous_archive_after_a_good_export(self, tmp_path):
        prelude = (
            "$old = Join-Path '__DEST__' 'Fake-Distro_2000-01-02.tar'; "
            "Set-Content -LiteralPath $old -Value 'old'; "
            "(Get-Item -LiteralPath $old).LastWriteTime = (Get-Date).AddDays(-40)"
        )
        proc, _calls, dest, _state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        names = [p.name for p in dest.iterdir()]
        assert len(names) == 1
        assert names[0] != "Fake-Distro_2000-01-02.tar"

    def test_pruning_touches_only_this_distros_archives(self, tmp_path):
        prelude = (
            "$other = Join-Path '__DEST__' 'Other-Distro_2000-01-02.tar'; "
            "Set-Content -LiteralPath $other -Value 'other'; "
            "(Get-Item -LiteralPath $other).LastWriteTime = (Get-Date).AddDays(-40)"
        )
        proc, _calls, dest, _state, _log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Other-Distro_2000-01-02.tar" in [p.name for p in dest.iterdir()]

    def test_a_skip_keeps_the_previous_archive(self, tmp_path):
        prelude = "Set-Content -LiteralPath (Join-Path '__DEST__' 'Fake-Distro_2000-01-02.tar') -Value 'old'"
        proc, _calls, dest, _state, _log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9 claude"), prelude=prelude
        )
        assert proc.returncode == 3
        assert [p.name for p in dest.iterdir()] == ["Fake-Distro_2000-01-02.tar"]


def _today(proc) -> str:
    """The run's own date, from the first log stamp it printed."""
    match = re.search(r"^(\d{4}-\d{2}-\d{2}) \d{2}:", proc.stdout, flags=re.M)
    assert match, proc.stdout
    return match.group(1)


_PARTIAL_THEN_FAIL = (
    "Set-Content -LiteralPath $args[-1] -Value 'partial'; $global:LASTEXITCODE = 5"
)


@windows
class TestOverdueAlert:
    """A missed export is not silent: FAILED, or overdue on a skip, raises a dialog."""

    def test_a_failed_export_is_logged_failed_and_raises_the_alert(self, tmp_path):
        proc, _calls, dest, _state, log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude="Set-LastOk 30", export=_PARTIAL_THEN_FAIL
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
        assert not list(dest.iterdir())
        assert "FAILED - " in log
        assert "SKIPPED" not in log
        alerts = _alerts(proc)
        assert len(alerts) == 1
        assert alerts[0].startswith("PARSE-ERRORS:0 powershell.exe ")
        assert "System.Windows.MessageBox" in alerts[0]
        assert "FAILED - wsl --export exited 5" in alerts[0]

    def test_the_alert_names_the_last_success_date(self, tmp_path):
        proc, _calls, _dest, _state, _log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9 claude"), prelude="Set-LastOk 36"
        )
        alerts = _alerts(proc)
        assert len(alerts) == 1
        # The reason text carries an apostrophe ("tonight's"); the command must still parse.
        assert alerts[0].startswith("PARSE-ERRORS:0 powershell.exe ")
        last = re.search(r"Last successful export: (\d{4}-\d{2}-\d{2})", alerts[0])
        assert last, alerts[0]
        today = date.fromisoformat(_today(proc))
        assert (today - date.fromisoformat(last.group(1))).days == 36

    def test_the_alert_carries_the_latest_blocker_from_the_log(self, tmp_path):
        prelude = (
            "Set-LastOk 40; "
            "Add-Content -LiteralPath (Join-Path '__STATE__' 'backup.log') "
            "-Value '2000-01-01 01:17:00  SKIPPED - busy (readiness exit 1); old news'"
        )
        proc, _calls, _dest, _state, _log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 4242 claude --resume"), prelude=prelude
        )
        alerts = _alerts(proc)
        assert len(alerts) == 1
        assert "BUSY - pid 4242 claude --resume" in alerts[0]
        assert "old news" not in alerts[0]

    @pytest.mark.parametrize(
        ("prelude", "alerted"),
        [("", True), ("Set-LastOk 36", True), ("Set-LastOk 35", False), ("Set-LastOk 30", False)],
        ids=["never-exported", "36-days", "35-days", "30-days"],
    )
    def test_a_skip_alerts_only_when_more_than_35_days_overdue(self, tmp_path, prelude, alerted):
        proc, calls, _dest, state, log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9 claude"), prelude=prelude
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert len(_alerts(proc)) == (1 if alerted else 0)
        assert (state / "alert.last-shown").exists() is alerted
        assert ("ALERT raised" in log) is alerted

    @pytest.mark.parametrize(
        ("export", "readiness"),
        [(_PARTIAL_THEN_FAIL, _readiness(0, "READY")), (_EXPORT_OK, _readiness(1, "BUSY - pid 9"))],
        ids=["failed", "overdue-skip"],
    )
    def test_the_alert_is_shown_at_most_once_per_calendar_day(self, tmp_path, export, readiness):
        prelude = (
            "Set-LastOk 40; "
            "Set-Content -LiteralPath (Join-Path '__STATE__' 'alert.last-shown') "
            "-Value (Get-Date -Format 'yyyy-MM-dd')"
        )
        proc, _calls, _dest, _state, log = _run_backup(
            tmp_path, readiness, prelude=prelude, export=export
        )
        assert _alerts(proc) == []
        assert "already shown today" in log

    def test_an_alert_marker_from_yesterday_does_not_suppress_today(self, tmp_path):
        prelude = (
            "Set-LastOk 40; "
            "Set-Content -LiteralPath (Join-Path '__STATE__' 'alert.last-shown') "
            "-Value (Get-Date).Date.AddDays(-1).ToString('yyyy-MM-dd')"
        )
        proc, _calls, _dest, state, _log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9"), prelude=prelude
        )
        assert len(_alerts(proc)) == 1
        assert (state / "alert.last-shown").read_text(encoding="utf-8").strip() == _today(proc)

    def test_an_alert_that_cannot_be_launched_still_exits_as_a_skip(self, tmp_path):
        prelude = "function Start-Process { throw 'no desktop session' }"
        proc, _calls, _dest, state, log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9"), prelude=prelude
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert "ALERT could not be shown" in log
        assert "no desktop session" in log
        assert not (state / "alert.last-shown").exists()

    @pytest.mark.parametrize(
        ("prelude", "reason"),
        [
            (
                "Remove-Item -LiteralPath '__DEST__' -Recurse -Force; "
                "function New-Item { throw 'Cannot find drive E' }",
                "Cannot find drive E",
            ),
            (
                "Set-Content -LiteralPath (Join-Path '__DEST__' "
                "('Fake-Distro_{0}.tar' -f (Get-Date -Format 'yyyy-MM-dd'))) -Value 'partial'; "
                "function Remove-Item { throw 'file is in use' }",
                "file is in use",
            ),
        ],
        ids=["dest-cannot-be-created", "todays-partial-is-locked"],
    )
    def test_a_failure_before_the_export_starts_is_failed_and_alerts(
        self, tmp_path, prelude, reason
    ):
        proc, calls, _dest, state, log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=f"Set-LastOk 60; {prelude}"
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert "FAILED - " in log and reason in log
        assert len(_alerts(proc)) == 1
        assert reason in _alerts(proc)[0]
        assert not (state / "export.last-ok").read_text(encoding="utf-8").strip() == _today(proc)

    def test_a_marker_dated_in_the_future_is_due_not_a_silent_no_op(self, tmp_path):
        # A clock that ran fast once must not suppress every export and alert after it.
        proc, calls, _dest, _state, log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude="Set-LastOk -400"
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert len(_exports(calls)) == 1
        assert "in the future" in log

    def test_a_future_marker_on_a_skip_raises_the_alert(self, tmp_path):
        proc, _calls, _dest, _state, _log = _run_backup(
            tmp_path, _readiness(1, "BUSY - pid 9"), prelude="Set-LastOk -400"
        )
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert len(_alerts(proc)) == 1
        assert "in the future" in _alerts(proc)[0]

    def test_a_successful_export_raises_no_alert(self, tmp_path):
        proc, _calls, _dest, _state, _log = _run_backup(tmp_path, _readiness(0, "READY"))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _alerts(proc) == []
