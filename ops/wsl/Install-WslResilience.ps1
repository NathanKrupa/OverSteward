# ABOUTME: Installer - deploy the WSL resilience scripts to a Windows path and register scheduled tasks.
# ABOUTME: NATHAN RUNS THIS on Windows (PowerShell). System-touching; review before running.
#requires -Version 5

<#
.SYNOPSIS
  Deploy the resilience scripts to a Windows-native folder and register two
  scheduled tasks: a weekly backup and a logon integrity check.

.DESCRIPTION
  WHY DEPLOY OUT OF THE REPO: the canonical scripts live in the OverSteward repo
  inside WSL (\\wsl.localhost\...). Task Scheduler cannot reliably reach that
  path - and the integrity check specifically must run even when WSL is broken,
  which is exactly when the WSL filesystem is unreachable. So this copies the
  scripts to a Windows-native folder and points the tasks there. Re-run after
  changing the repo scripts to redeploy.

  Tasks registered (in the current user's context, "run only when logged on",
  so no stored password is needed):
    - "WSL Weekly Backup"        -> Backup-Wsl.ps1 (weekly; catches up if missed)
    - "WSL Integrity Check"      -> Test-WslIntegrity.ps1 at logon; pops an alert
                                    dialog if the platform is broken.

  This does NOT change update settings - run Set-WslUpdatePolicy.ps1 separately
  (elevated) if you want the Store auto-download key set.

.PARAMETER InstallDir
  Windows folder to deploy scripts into. Default: %LOCALAPPDATA%\WslResilience.

.PARAMETER BackupDest
  Passed to the weekly backup task. Default: E:\WSLBackups.

.PARAMETER Distro
  Distro to back up. Default: Ubuntu-24.04.

.PARAMETER WeeklyDay
  Day of week for the backup. Default: Sunday.

.PARAMETER WeeklyTime
  Time of day (HH:mm) for the backup. Default: 03:17 (off the round hour).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'WslResilience'),
    [string]$BackupDest = 'E:\WSLBackups',
    [string]$Distro = 'Ubuntu-24.04',
    [ValidateSet('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')]
    [string]$WeeklyDay = 'Sunday',
    [string]$WeeklyTime = '03:17'
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

# 2. Weekly backup task.
$backupArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$backupPath`" -Distro `"$Distro`" -Dest `"$BackupDest`""
$backupAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $backupArgs
$backupTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $WeeklyTime
$backupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)
if ($PSCmdlet.ShouldProcess('WSL Weekly Backup', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Weekly Backup' -Action $backupAction -Trigger $backupTrigger `
        -Settings $backupSettings -Description "Weekly wsl --export of $Distro to $BackupDest (OverSteward WSL resilience)." -Force | Out-Null
    Write-Host "Registered 'WSL Weekly Backup' ($WeeklyDay $WeeklyTime)." -ForegroundColor Green
}

# 3. Logon integrity check with an alert dialog on failure.
$logonCmd = "& '$gatePath' -Quiet; if (`$LASTEXITCODE -ne 0) { Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show('WSL integrity check FAILED - system.vhd/modules.vhd may be missing (microsoft/WSL #40616 class). See the wsl-recovery runbook before trusting this machine.','WSL RESILIENCE ALERT','OK','Error') }"
$logonArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$logonCmd`""
$logonAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $logonArgs
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$logonSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
if ($PSCmdlet.ShouldProcess('WSL Integrity Check', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Integrity Check' -Action $logonAction -Trigger $logonTrigger `
        -Settings $logonSettings -Description 'At-logon WSL platform integrity check; alerts if broken (OverSteward WSL resilience).' -Force | Out-Null
    Write-Host "Registered 'WSL Integrity Check' (at logon)." -ForegroundColor Green
}

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName 'WSL *'" -ForegroundColor Cyan
Write-Host "Run a backup now to validate + measure size:  powershell -File `"$backupPath`""
Write-Host "Uninstall:  Unregister-ScheduledTask -TaskName 'WSL Weekly Backup','WSL Integrity Check' -Confirm:`$false"
