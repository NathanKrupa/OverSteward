# ABOUTME: Tests for ops/wsl/Test-WslIntegrity.ps1, the logon canary, and the installer's logon task.
# ABOUTME: Text checks always run; behaviour runs the real gate under Windows PowerShell with wsl.exe faked.

"""The logon canary must alert on a stale backup even when WSL is dead.

The gate reads only Windows paths: the VM-platform VHDs under
``$env:ProgramFiles``, the C: mirror of ``restic.last-ok`` that the daily home
backup writes, and the dated archives on the export drive. Each behaviour test
builds those three in a temp dir, points ``$env:ProgramFiles`` at it, shadows
``wsl.exe`` with a PowerShell function, and runs the real script, so nothing
reaches the real platform. Times are computed inside PowerShell, from UTC, so a
fixture's age is exact whatever the clock's zone or a DST change in between.
"""

from __future__ import annotations

import re
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from oversteward.backup import health
from tests.backup.test_backup_wsl_ps1 import _POWERSHELL, _code, _win, windows

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "ops" / "wsl" / "Test-WslIntegrity.ps1"
INSTALLER = REPO_ROOT / "ops" / "wsl" / "Install-WslResilience.ps1"
UPDATER = REPO_ROOT / "ops" / "wsl" / "Update-WslSafely.ps1"

DISTRO = "Fake-Distro"
VHD_DIALOG_LITERAL = "system.vhd/modules.vhd may be missing"


# --- text checks: always run ------------------------------------------------


class TestThresholdParity:
    """health.py and the gate hold the backups to one standard, with no shared file."""

    def test_restic_hours_match_the_sweep(self):
        match = re.search(r"\[int\]\$ResticMaxHours\s*=\s*(\d+)\b", _code(GATE))
        assert match, "Test-WslIntegrity.ps1 declares no -ResticMaxHours default"
        assert timedelta(hours=int(match[1])) == health.SNAPSHOT_MAX_AGE

    def test_export_days_match_the_sweep(self):
        match = re.search(r"\[int\]\$ExportMaxDays\s*=\s*(\d+)\b", _code(GATE))
        assert match, "Test-WslIntegrity.ps1 declares no -ExportMaxDays default"
        assert timedelta(days=int(match[1])) == health.EXPORT_MAX_AGE


class TestGateText:
    def test_reads_nothing_inside_the_distro(self):
        # The gate must work with WSL dead, so no path may resolve through it.
        text = GATE.read_text(encoding="utf-8").lower()
        assert "wsl$" not in text
        assert "wsl.localhost" not in text
        assert "/mnt/" not in text

    def test_defaults_name_the_live_locations(self):
        code = _code(GATE)
        assert re.search(r"\[string\]\$StateDir\s*=\s*\(Join-Path \$env:LOCALAPPDATA 'WslResilience'\)", code)
        assert re.search(r"\[string\]\$BackupDest\s*=\s*'E:\\WSLBackups'", code)
        assert re.search(r"\[string\]\$Distro\s*=\s*'Ubuntu-24.04'", code)

    def test_parses_the_marker_as_pr_a_writes_it(self):
        assert "'yyyy-MM-dd\\THH:mm:ss'" in _code(GATE)


class TestInstallerText:
    def test_the_dialog_carries_the_gate_output_not_a_fixed_vhd_message(self):
        code = _code(INSTALLER)
        assert VHD_DIALOG_LITERAL not in code
        assert "*>&1" in code

    def test_the_logon_trigger_is_delayed_thirty_minutes(self):
        assert re.search(r"\$logonTrigger\.Delay\s*=\s*'PT30M'", _code(INSTALLER))

    def test_the_gate_is_given_the_state_dir_backup_dest_and_distro(self):
        code = _code(INSTALLER)
        line = next(line for line in code.splitlines() if line.lstrip().startswith("$logonCmd ="))
        assert "-StateDir '$InstallDir'" in line
        assert "-BackupDest '$BackupDest'" in line
        assert "-Distro '$Distro'" in line

    def test_the_verify_line_is_still_printed(self):
        assert "Get-ScheduledTask -TaskName 'WSL *'" in _code(INSTALLER)

    def test_the_backup_task_keeps_its_name(self):
        assert "-TaskName 'WSL Monthly Backup'" in _code(INSTALLER)


class TestUpdaterText:
    def test_the_update_gate_checks_only_the_platform(self):
        # A stale backup must never roll back a healthy WSL update.
        assert re.search(r"-File \$gate -PlatformOnly\b", _code(UPDATER))


# --- behaviour checks: Windows PowerShell with wsl.exe faked ----------------

_GATE_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$env:ProgramFiles = '__PF__'
function wsl.exe { $global:LASTEXITCODE = __WSLCODE__ }
function Set-Marker([double]$hoursAgo) {
    $stamp = [DateTime]::UtcNow.AddHours(-$hoursAgo).ToLocalTime().ToString("yyyy-MM-dd'T'HH:mm:ss")
    Set-Marker-Raw "$stamp 0123456789abcdef`n"
}
function Set-Marker-Raw([string]$raw) {
    [IO.File]::WriteAllText((Join-Path '__STATE__' 'restic.last-ok'), $raw)
}
function New-Archive([int]$daysAgo, [string]$content) {
    $name = '__DISTRO___' + (Get-Date).Date.AddDays(-$daysAgo).ToString('yyyy-MM-dd') + '.tar'
    [IO.File]::WriteAllText((Join-Path '__DEST__' $name), $content)
}
__PRELUDE__
$out = & '__GATE__' __ARGS__ *>&1 | Out-String
$code = $LASTEXITCODE
Write-Output $out
exit $code
"""

_HEALTHY = "Set-Marker 1; New-Archive 2 'archive'"


def _platform(tmp_path: Path, system_vhd: bytes = b"vhd") -> Path:
    pf = tmp_path / "pf"
    (pf / "WSL" / "tools").mkdir(parents=True)
    (pf / "WSL" / "system.vhd").write_bytes(system_vhd)
    (pf / "WSL" / "tools" / "modules.vhd").write_bytes(b"vhd")
    return pf


def _run_gate(
    tmp_path: Path,
    prelude: str = _HEALTHY,
    system_vhd: bytes = b"vhd",
    wsl_code: int = 0,
    extra: str = "",
    make_dest: bool = True,
    gate_args: bool = True,
) -> subprocess.CompletedProcess[str]:
    pf = _platform(tmp_path, system_vhd)
    state = tmp_path / "state"
    dest = tmp_path / "dest"
    state.mkdir()
    if make_dest:
        dest.mkdir()
    args = (
        f"-StateDir '{_win(state)}' -BackupDest '{_win(dest)}' -Distro '{DISTRO}' {extra}"
        if gate_args
        else extra
    )
    harness = (
        _GATE_HARNESS.replace("__PRELUDE__", prelude)
        .replace("__PF__", _win(pf))
        .replace("__STATE__", _win(state))
        .replace("__DEST__", _win(dest))
        .replace("__DISTRO__", DISTRO)
        .replace("__WSLCODE__", str(wsl_code))
        .replace("__GATE__", _win(GATE))
        .replace("__ARGS__", args)
    )
    wrapper = tmp_path / "harness.ps1"
    wrapper.write_text(harness, encoding="utf-8")
    return subprocess.run(
        [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _win(wrapper)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _said(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


@windows
class TestPlatformBehaviour:
    def test_a_zero_length_system_vhd_fails(self, tmp_path):
        proc = _run_gate(tmp_path, system_vhd=b"")
        assert proc.returncode == 1, _said(proc)
        assert "ZERO-LENGTH:" in proc.stdout
        assert "system.vhd" in proc.stdout

    def test_a_healthy_platform_and_current_backups_pass(self, tmp_path):
        proc = _run_gate(tmp_path)
        assert proc.returncode == 0, _said(proc)
        assert "RESTIC" not in proc.stdout
        assert "EXPORT" not in proc.stdout


@windows
class TestResticBehaviour:
    def test_a_mirror_49_hours_old_fails_naming_restic(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 49; New-Archive 2 'a'")
        assert proc.returncode == 1, _said(proc)
        assert "RESTIC: last verified backup" in proc.stdout
        assert "limit 48 h" in proc.stdout

    def test_a_mirror_47_hours_old_passes(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 47; New-Archive 2 'a'")
        assert proc.returncode == 0, _said(proc)
        assert "RESTIC" not in proc.stdout

    def test_a_mirror_dated_in_the_future_fails(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker -2; New-Archive 2 'a'")
        assert proc.returncode == 1, _said(proc)
        assert "RESTIC:" in proc.stdout
        assert "in the future" in proc.stdout

    def test_an_absent_mirror_fails(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="New-Archive 2 'a'")
        assert proc.returncode == 1, _said(proc)
        assert "RESTIC: no verified backup on record" in proc.stdout

    @pytest.mark.parametrize(
        "raw",
        ["garbage d0bfed74\n", "2026-10-14 04:00:12 d0bfed74\n", ""],
        ids=["not-a-date", "space-not-T", "empty"],
    )
    def test_an_unparseable_mirror_fails(self, tmp_path, raw):
        proc = _run_gate(tmp_path, prelude=f"Set-Marker-Raw '{raw}'; New-Archive 2 'a'")
        assert proc.returncode == 1, _said(proc)
        assert "RESTIC:" in proc.stdout
        assert "unparseable" in proc.stdout

    def test_only_the_first_token_is_the_timestamp(self, tmp_path):
        # PR A writes "<stamp> <snapshot id>\n"; a CRLF rewrite must not break it.
        stamp = "[DateTime]::UtcNow.AddHours(-1).ToLocalTime().ToString(\"yyyy-MM-dd'T'HH:mm:ss\")"
        prelude = f"Set-Marker-Raw (({stamp}) + ' d0bfed74' + [char]13 + [char]10); New-Archive 2 'a'"
        proc = _run_gate(tmp_path, prelude=prelude)
        assert proc.returncode == 0, _said(proc)


@windows
class TestExportBehaviour:
    def test_an_archive_46_days_old_fails_naming_export(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 1; New-Archive 46 'a'")
        assert proc.returncode == 1, _said(proc)
        assert "EXPORT:" in proc.stdout
        assert "46 days old (limit 45 days)" in proc.stdout

    def test_an_archive_44_days_old_passes(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 1; New-Archive 44 'a'")
        assert proc.returncode == 0, _said(proc)
        assert "EXPORT" not in proc.stdout

    def test_a_zero_byte_newest_archive_fails(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 1; New-Archive 50 'old'; New-Archive 1 ''")
        assert proc.returncode == 1, _said(proc)
        assert "EXPORT:" in proc.stdout
        assert "zero bytes" in proc.stdout

    def test_the_newest_is_chosen_by_the_date_in_its_name(self, tmp_path):
        # A stale archive written last must not hide behind its write time.
        prelude = (
            "Set-Marker 1; New-Archive 2 'new'; New-Archive 60 'old'; "
            "(Get-Item -LiteralPath (Join-Path '__DEST__' ('__DISTRO___' + "
            "(Get-Date).Date.AddDays(-2).ToString('yyyy-MM-dd') + '.tar'))).LastWriteTime = "
            "(Get-Date).AddDays(-90)"
        )
        proc = _run_gate(tmp_path, prelude=prelude)
        assert proc.returncode == 0, _said(proc)

    def test_no_archive_fails(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 1")
        assert proc.returncode == 1, _said(proc)
        assert f"EXPORT: no {DISTRO}_YYYY-MM-DD.tar" in proc.stdout

    def test_another_distros_archive_does_not_count(self, tmp_path):
        prelude = (
            "Set-Marker 1; [IO.File]::WriteAllText((Join-Path '__DEST__' "
            "('Other-Distro_' + (Get-Date).ToString('yyyy-MM-dd') + '.tar')), 'a')"
        )
        proc = _run_gate(tmp_path, prelude=prelude)
        assert proc.returncode == 1, _said(proc)
        assert f"EXPORT: no {DISTRO}_YYYY-MM-DD.tar" in proc.stdout

    def test_the_distro_name_matches_case_sensitively_as_the_sweep_does(self, tmp_path):
        prelude = (
            "Set-Marker 1; [IO.File]::WriteAllText((Join-Path '__DEST__' "
            "('" + DISTRO.lower() + "_' + (Get-Date).ToString('yyyy-MM-dd') + '.tar')), 'a')"
        )
        proc = _run_gate(tmp_path, prelude=prelude)
        assert proc.returncode == 1, _said(proc)
        assert f"EXPORT: no {DISTRO}_YYYY-MM-DD.tar" in proc.stdout

    def test_an_unreachable_backup_dest_fails(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 1", make_dest=False)
        assert proc.returncode == 1, _said(proc)
        assert "EXPORT: backup destination" in proc.stdout
        assert "unreachable" in proc.stdout


@windows
class TestPlatformOnly:
    def test_platform_only_ignores_stale_backups(self, tmp_path):
        proc = _run_gate(tmp_path, prelude="Set-Marker 99", make_dest=False, extra="-PlatformOnly")
        assert proc.returncode == 0, _said(proc)

    def test_platform_only_still_fails_a_broken_platform(self, tmp_path):
        proc = _run_gate(tmp_path, system_vhd=b"", extra="-PlatformOnly")
        assert proc.returncode == 1, _said(proc)
        assert "ZERO-LENGTH:" in proc.stdout


# --- the installer's logon task, end to end ---------------------------------

_INSTALL_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:Actions = New-Object System.Collections.ArrayList
$global:Triggers = New-Object System.Collections.ArrayList
function New-ScheduledTaskAction { param($Execute, $Argument)
    $a = [pscustomobject]@{ Execute = $Execute; Argument = $Argument }
    [void]$global:Actions.Add($a); $a }
function New-ScheduledTaskTrigger { param([switch]$Daily, [switch]$Once, [switch]$AtLogOn, $At, $User,
        $RepetitionInterval, $RepetitionDuration)
    $t = [pscustomobject]@{ AtLogOn = [bool]$AtLogOn; Delay = $null;
        Repetition = [pscustomobject]@{ StopAtDurationEnd = $true } }
    [void]$global:Triggers.Add($t); $t }
function New-ScheduledTaskSettingsSet { [pscustomobject]@{} }
function Get-ScheduledTask { $null }
function Register-ScheduledTask { throw 'Register-ScheduledTask reached under test' }
function Unregister-ScheduledTask { throw 'Unregister-ScheduledTask reached under test' }
& '__INSTALLER__' -InstallDir '__INSTALL__' -BackupDest '__DEST__' -Distro '__DISTRO__' -WhatIf *> $null
foreach ($a in $global:Actions) { Write-Output "ACTION: $($a.Argument)" }
foreach ($t in $global:Triggers) { if ($t.AtLogOn) { Write-Output "LOGON-DELAY: $($t.Delay)" } }
"""

_DIALOG_HARNESS = r"""
class FakeBox {
    static [string] Show([string]$text, [string]$title, [string]$buttons, [string]$icon) {
        [IO.File]::WriteAllText('__DIALOG__', $title + '|' + $text)
        return 'OK'
    }
}
$env:ProgramFiles = '__PF__'
function wsl.exe { $global:LASTEXITCODE = 0 }
function Add-Type { }
__PRELUDE__
__COMMAND__
"""


def _install(tmp_path: Path, gate: bytes | None = None) -> tuple[str, str, Path, Path]:
    """Run the installer under -WhatIf with the task cmdlets faked; return its logon command."""
    install = tmp_path / "install"
    dest = tmp_path / "dest"
    install.mkdir()
    dest.mkdir()
    # -WhatIf skips the deploy, so put the gate where the deploy would have.
    (install / GATE.name).write_bytes(GATE.read_bytes() if gate is None else gate)
    harness = (
        _INSTALL_HARNESS.replace("__INSTALLER__", _win(INSTALLER))
        .replace("__INSTALL__", _win(install))
        .replace("__DEST__", _win(dest))
        .replace("__DISTRO__", DISTRO)
    )
    wrapper = tmp_path / "install.ps1"
    wrapper.write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _win(wrapper)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, _said(proc)
    logon = [
        line.removeprefix("ACTION: ")
        for line in proc.stdout.splitlines()
        if line.startswith("ACTION: ") and "Test-WslIntegrity.ps1" in line
    ]
    delays = [
        line.removeprefix("LOGON-DELAY: ").strip()
        for line in proc.stdout.splitlines()
        if line.startswith("LOGON-DELAY: ")
    ]
    assert len(logon) == 1, proc.stdout
    assert len(delays) == 1, proc.stdout
    command = re.fullmatch(r'.*-Command "(.*)"', logon[0].strip())
    assert command, logon[0]
    return command[1], delays[0], install, dest


def _logon(tmp_path: Path, prelude: str, gate: bytes | None = None) -> str | None:
    """Run the installed logon command against a faked machine; return the dialog, if any."""
    command, _delay, install, dest = _install(tmp_path, gate)
    assert command.count("[System.Windows.MessageBox]::Show(") == 1, command
    dialog = tmp_path / "dialog.txt"
    pf = _platform(tmp_path)
    harness = (
        _DIALOG_HARNESS.replace("__DIALOG__", _win(dialog))
        .replace("__PF__", _win(pf))
        .replace("__PRELUDE__", prelude.replace("__STATE__", _win(install)).replace("__DEST__", _win(dest)))
        .replace("__COMMAND__", command.replace("[System.Windows.MessageBox]::Show(", "[FakeBox]::Show("))
    )
    wrapper = tmp_path / "logon.ps1"
    wrapper.write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _win(wrapper)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "reached under test" not in _said(proc)
    return dialog.read_text(encoding="utf-8") if dialog.exists() else None


_MARKER = (
    "[IO.File]::WriteAllText((Join-Path '__STATE__' 'restic.last-ok'), "
    "[DateTime]::UtcNow.AddHours(-{hours}).ToLocalTime().ToString(\"yyyy-MM-dd'T'HH:mm:ss\") + ' ab`n'); "
    "[IO.File]::WriteAllText((Join-Path '__DEST__' ('" + DISTRO + "_' + "
    "(Get-Date).Date.AddDays(-2).ToString('yyyy-MM-dd') + '.tar')), 'a')"
)


@windows
class TestInstalledLogonTask:
    def test_the_logon_trigger_waits_thirty_minutes(self, tmp_path):
        _command, delay, _install_dir, _dest = _install(tmp_path)
        assert delay == "PT30M"

    def test_a_stale_backup_shows_the_gate_output_in_the_dialog(self, tmp_path):
        dialog = _logon(tmp_path, _MARKER.format(hours=72))
        assert dialog is not None
        assert dialog.startswith("WSL RESILIENCE ALERT|")
        assert "RESTIC: last verified backup" in dialog
        assert VHD_DIALOG_LITERAL not in dialog

    def test_current_backups_show_no_dialog(self, tmp_path):
        assert _logon(tmp_path, _MARKER.format(hours=1)) is None

    def test_a_gate_that_throws_still_shows_a_dialog(self, tmp_path):
        # A drive that errors on read must not leave the hidden logon task silent.
        gate = b"$ErrorActionPreference = 'Stop'\r\nthrow 'E: went away'\r\nexit 0\r\n"
        dialog = _logon(tmp_path, _MARKER.format(hours=1), gate=gate)
        assert dialog is not None
        assert "could not run" in dialog
        assert "E: went away" in dialog
