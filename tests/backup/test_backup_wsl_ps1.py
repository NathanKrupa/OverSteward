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


class TestInstallerText:
    def test_schedules_the_first_sunday_of_every_month(self):
        code = _code(INSTALLER)
        assert "MSFT_TaskMonthlyDOWTrigger" in code
        assert re.search(r"WeeksOfMonth\s*=\s*1\b", code)
        assert re.search(r"DaysOfWeek\s*=\s*1\b", code)  # bit 1 = Sunday
        assert re.search(r"MonthOfYear\s*=\s*4095\b", code)  # all twelve months

    def test_starts_at_0517_and_retries_hourly_for_seventeen_hours(self):
        code = _code(INSTALLER)
        assert "'05:17'" in code
        assert "'PT1H'" in code
        assert "'PT17H'" in code

    def test_no_weekly_trigger_remains(self):
        assert "-Weekly" not in _code(INSTALLER)

    def test_removes_the_weekly_task_it_replaces(self):
        assert re.search(r"Unregister-ScheduledTask\s+-TaskName\s+'WSL Weekly Backup'\s+-Confirm:\$false",
                         _code(INSTALLER))


class TestDocsText:
    @pytest.mark.parametrize("doc", [README, RUNBOOK], ids=["readme", "runbook"])
    @pytest.mark.parametrize("phrase", ["weekly", "03:17", "stops the distro"])
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


_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:WslCalls = New-Object System.Collections.ArrayList
function __FAKENAME__ {
    [void]$global:WslCalls.Add(($args -join ' '))
    if ($args -contains '--export') {
        Set-Content -LiteralPath $args[-1] -Value 'archive' -Encoding ASCII
        $global:LASTEXITCODE = 0
        return
    }
    __READINESS__
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
):
    dest = tmp_path / "dest"
    state = tmp_path / "state"
    dest.mkdir()
    state.mkdir()
    harness = (
        _HARNESS.replace("__FAKENAME__", "unused-fake" if real_wsl else "wsl.exe")
        .replace("'Fake-Distro'", f"'{distro}'")
        .replace("__READINESS__", readiness)
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
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert _exports(calls) == []
        assert not list(dest.iterdir())
        assert not (state / "export.last-ok").exists()
        assert line in log
        assert f"readiness exit {code}" in log

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

    def test_a_marker_dated_today_exits_zero_without_touching_wsl(self, tmp_path):
        prelude = (
            "Set-Content -LiteralPath (Join-Path '__STATE__' 'export.last-ok') "
            "-Value (Get-Date -Format 'yyyy-MM-dd')"
        )
        proc, calls, dest, _state, log = _run_backup(
            tmp_path, _readiness(0, "READY"), prelude=prelude
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert calls == []
        assert not list(dest.iterdir())
        assert "already" in log.lower()

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
