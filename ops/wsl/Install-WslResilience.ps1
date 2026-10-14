# ABOUTME: Installer - deploy the WSL resilience scripts to a Windows path and register scheduled tasks.
# ABOUTME: NATHAN RUNS THIS on Windows (PowerShell). System-touching; review before running.
#requires -Version 5

<#
.SYNOPSIS
  Deploy the resilience scripts to a Windows-native folder and register two
  scheduled tasks: a nightly due- and readiness-gated backup attempt (an export
  roughly every 28 days) and a logon integrity check.

.DESCRIPTION
  WHY DEPLOY OUT OF THE REPO: the canonical scripts live in the OverSteward repo
  inside WSL (\\wsl.localhost\...). Task Scheduler cannot reliably reach that
  path - and the integrity check specifically must run even when WSL is broken,
  which is exactly when the WSL filesystem is unreachable. So this copies the
  scripts to a Windows-native folder and points the tasks there. Re-run after
  changing the repo scripts to redeploy.

  Tasks registered (in the current user's context, "run only when logged on",
  so no stored password is needed):
    - "WSL Monthly Backup"       -> Backup-Wsl.ps1 every night at 01:17,
                                    repeating hourly for 5 hours (to ~06:17).
                                    A run exits 0 at once unless an export is
                                    due (last success 28+ days ago, or none),
                                    so the export happens about monthly, and a
                                    skipped or failed attempt is retried the
                                    next night. It exports only when the
                                    distro is idle and exits 3 otherwise; it
                                    never kills the work its probes see
                                    (working Claude Code sessions, detached
                                    GrantSpider runs, estate job services,
                                    docker containers). A FAILED export, or a
                                    skip more than 35 days after the last
                                    success, pops an alert dialog, at most
                                    once a day.
    - "WSL Integrity Check"      -> Test-WslIntegrity.ps1 30 minutes after logon;
                                    pops an alert dialog carrying the gate's own
                                    output if the platform is broken or either
                                    backup is behind (restic.last-ok in
                                    InstallDir over 48 h, newest export in
                                    BackupDest over 45 days). The delay lets
                                    home-backup.timer's Persistent catch-up run
                                    first after a closed weekend, so the canary
                                    judges the marker it writes.

  The trigger is a plain daily one; Backup-Wsl.ps1 decides whether an export is
  due. A monthly day-of-week trigger (MSFT_TaskMonthlyDOWTrigger) was refused
  by Register-ScheduledTask with 0x80070057 "The parameter is incorrect" on
  this machine (2026-10-11). The retired weekly backup task, if present from
  an earlier install, is unregistered.

  This does NOT change update settings - run Set-WslUpdatePolicy.ps1 separately
  (elevated) if you want the Store auto-download key set.

.PARAMETER InstallDir
  Windows folder to deploy scripts into. Default: %LOCALAPPDATA%\WslResilience.

.PARAMETER BackupDest
  Passed to the backup task and the logon check. Default: E:\WSLBackups.

.PARAMETER Distro
  Distro to back up, and whose archives the logon check reads. Default: Ubuntu-24.04.

.PARAMETER DailyTime
  Time of day (HH:mm) of the first nightly attempt. Default: 01:17 (off the
  round hour, while nobody is working). Attempts repeat hourly for 5 hours
  from here.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'WslResilience'),
    [string]$BackupDest = 'E:\WSLBackups',
    [string]$Distro = 'Ubuntu-24.04',
    [string]$DailyTime = '01:17'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Deploy scripts to a Windows-native folder.
if (-not (Test-Path -LiteralPath $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
$scripts = @('Test-WslIntegrity.ps1', 'Update-WslSafely.ps1', 'Backup-Wsl.ps1', 'Set-WslUpdatePolicy.ps1')
foreach ($s in $scripts) {
    Copy-Item -LiteralPath (Join-Path $here $s) -Destination (Join-Path $InstallDir $s) -Force
}
Write-Host "Deployed scripts to $InstallDir" -ForegroundColor Green

$gatePath = Join-Path $InstallDir 'Test-WslIntegrity.ps1'
$backupPath = Join-Path $InstallDir 'Backup-Wsl.ps1'

# 2. Backup task: nightly, retried hourly; Backup-Wsl.ps1 exits 0 unless an export is due.
$backupArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$backupPath`" -Distro `"$Distro`" -Dest `"$BackupDest`" -StateDir `"$InstallDir`""
$backupAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $backupArgs
$backupTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
# A -Daily trigger takes no repetition switches; borrow the pattern from a -Once trigger.
$backupTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At $DailyTime -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 5)).Repetition
# The borrowed pattern stops a running instance when the window ends; an export
# started on the last retry must run to completion (bounded by ExecutionTimeLimit).
$backupTrigger.Repetition.StopAtDurationEnd = $false
$backupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)
if ($PSCmdlet.ShouldProcess('WSL Monthly Backup', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Monthly Backup' -Action $backupAction -Trigger $backupTrigger `
        -Settings $backupSettings -Description "Nightly attempt at a due (28+ days) readiness-gated wsl --export of $Distro to $BackupDest; skips while busy, alerts when overdue (OverSteward WSL resilience)." -Force | Out-Null
    Write-Host "Registered 'WSL Monthly Backup' (nightly $DailyTime, hourly retries for 5h, exports when due)." -ForegroundColor Green
}
if ((Get-ScheduledTask -TaskName 'WSL Weekly Backup' -ErrorAction SilentlyContinue) -and
    $PSCmdlet.ShouldProcess('WSL Weekly Backup', 'Unregister-ScheduledTask')) {
    Unregister-ScheduledTask -TaskName 'WSL Weekly Backup' -Confirm:$false
    Write-Host "Removed the retired weekly backup task." -ForegroundColor Green
}

# 3. Logon integrity check; on failure the dialog shows the gate's own output,
#    which names each problem (VHD, WSL, RESTIC, EXPORT). A gate that throws
#    alerts too: the task runs hidden, so an uncaught error would be silent.
$logonCmd = "try { `$out = & '$gatePath' -Quiet -StateDir '$InstallDir' -BackupDest '$BackupDest' -Distro '$Distro' *>&1 | Out-String; `$code = `$LASTEXITCODE } catch { `$out = 'WSL integrity check could not run: ' + `$_; `$code = 1 }; if (`$code -ne 0) { Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show(`$out,'WSL RESILIENCE ALERT','OK','Error') }"
$logonArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$logonCmd`""
$logonAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $logonArgs
# Scope the logon trigger to the current user — a bare -AtLogOn is an "any user"
# (machine-wide) trigger that requires elevation; per-user does not.
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# Wait 30 minutes: after days closed, home-backup.timer's Persistent catch-up runs
# once the distro starts, and the restic marker should be judged after it. Its
# runs take well under a minute (journalctl --user -u home-backup, 2026-10-14).
$logonTrigger.Delay = 'PT30M'
$logonSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
if ($PSCmdlet.ShouldProcess('WSL Integrity Check', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Integrity Check' -Action $logonAction -Trigger $logonTrigger `
        -Settings $logonSettings -Description 'WSL platform integrity and backup-age check 30 minutes after logon; alerts if broken or behind (OverSteward WSL resilience).' -Force | Out-Null
    Write-Host "Registered 'WSL Integrity Check' (30 minutes after logon)." -ForegroundColor Green
}

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName 'WSL *'" -ForegroundColor Cyan
Write-Host "Run a backup now to validate + measure size:  powershell -File `"$backupPath`""
Write-Host "Backup log + markers:  $InstallDir\backup.log, $InstallDir\export.last-ok, $InstallDir\alert.last-shown"
Write-Host "Uninstall:  Unregister-ScheduledTask -TaskName 'WSL Monthly Backup','WSL Integrity Check' -Confirm:`$false"
