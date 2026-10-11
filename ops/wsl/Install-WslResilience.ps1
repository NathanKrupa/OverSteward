# ABOUTME: Installer - deploy the WSL resilience scripts to a Windows path and register scheduled tasks.
# ABOUTME: NATHAN RUNS THIS on Windows (PowerShell). System-touching; review before running.
#requires -Version 5

<#
.SYNOPSIS
  Deploy the resilience scripts to a Windows-native folder and register two
  scheduled tasks: a monthly readiness-gated backup and a logon integrity check.

.DESCRIPTION
  WHY DEPLOY OUT OF THE REPO: the canonical scripts live in the OverSteward repo
  inside WSL (\\wsl.localhost\...). Task Scheduler cannot reliably reach that
  path - and the integrity check specifically must run even when WSL is broken,
  which is exactly when the WSL filesystem is unreachable. So this copies the
  scripts to a Windows-native folder and points the tasks there. Re-run after
  changing the repo scripts to redeploy.

  Tasks registered (in the current user's context, "run only when logged on",
  so no stored password is needed):
    - "WSL Monthly Backup"       -> Backup-Wsl.ps1 on the first Sunday of every
                                    month at 05:17 (after the 03:30 dream cycle),
                                    repeating hourly for 17 hours (to ~22:17).
                                    Backup-Wsl.ps1 exports only when the distro is
                                    idle and exits 3 otherwise, so each repeat is a
                                    retry; after one success the day's marker makes
                                    the rest no-ops. It never kills the work
                                    its probes see (Claude Code sessions,
                                    estate job services, docker containers).
    - "WSL Integrity Check"      -> Test-WslIntegrity.ps1 at logon; pops an alert
                                    dialog if the platform is broken.

  The schedule uses the MSFT_TaskMonthlyDOWTrigger CIM class, because
  New-ScheduledTaskTrigger has no -Monthly. The retired weekly backup task, if
  present from an earlier install, is unregistered.

  This does NOT change update settings - run Set-WslUpdatePolicy.ps1 separately
  (elevated) if you want the Store auto-download key set.

.PARAMETER InstallDir
  Windows folder to deploy scripts into. Default: %LOCALAPPDATA%\WslResilience.

.PARAMETER BackupDest
  Passed to the monthly backup task. Default: E:\WSLBackups.

.PARAMETER Distro
  Distro to back up. Default: Ubuntu-24.04.

.PARAMETER MonthlyTime
  Time of day (HH:mm) of the first attempt on the first Sunday. Default: 05:17
  (off the round hour, after the dream cycle). Attempts repeat hourly for 17
  hours from here.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'WslResilience'),
    [string]$BackupDest = 'E:\WSLBackups',
    [string]$Distro = 'Ubuntu-24.04',
    [string]$MonthlyTime = '05:17'
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

# 2. Monthly backup task: first Sunday, retried hourly while the distro is busy.
$backupArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$backupPath`" -Distro `"$Distro`" -Dest `"$BackupDest`" -StateDir `"$InstallDir`""
$backupAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $backupArgs
$taskNs = 'Root/Microsoft/Windows/TaskScheduler'
$backupTrigger = New-CimInstance -CimClass (Get-CimClass -Namespace $taskNs -ClassName 'MSFT_TaskMonthlyDOWTrigger') -ClientOnly
$backupTrigger.DaysOfWeek = 1        # bitmask: 1 = Sunday
$backupTrigger.WeeksOfMonth = 1      # bitmask: 1 = the first week, so the first Sunday
$backupTrigger.MonthOfYear = 4095    # bitmask: all twelve months
$backupTrigger.StartBoundary = '{0}T{1}:00' -f (Get-Date -Format 'yyyy-MM-dd'), $MonthlyTime
$backupTrigger.Enabled = $true
$retry = New-CimInstance -CimClass (Get-CimClass -Namespace $taskNs -ClassName 'MSFT_TaskRepetitionPattern') -ClientOnly
$retry.Interval = 'PT1H'
$retry.Duration = 'PT17H'
$retry.StopAtDurationEnd = $false
$backupTrigger.Repetition = $retry
$backupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 3)
if ($PSCmdlet.ShouldProcess('WSL Monthly Backup', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Monthly Backup' -Action $backupAction -Trigger $backupTrigger `
        -Settings $backupSettings -Description "Monthly readiness-gated wsl --export of $Distro to $BackupDest; skips while busy (OverSteward WSL resilience)." -Force | Out-Null
    Write-Host "Registered 'WSL Monthly Backup' (first Sunday $MonthlyTime, hourly retries for 17h)." -ForegroundColor Green
}
if ((Get-ScheduledTask -TaskName 'WSL Weekly Backup' -ErrorAction SilentlyContinue) -and
    $PSCmdlet.ShouldProcess('WSL Weekly Backup', 'Unregister-ScheduledTask')) {
    Unregister-ScheduledTask -TaskName 'WSL Weekly Backup' -Confirm:$false
    Write-Host "Removed the retired weekly backup task." -ForegroundColor Green
}

# 3. Logon integrity check with an alert dialog on failure.
$logonCmd = "& '$gatePath' -Quiet; if (`$LASTEXITCODE -ne 0) { Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show('WSL integrity check FAILED - system.vhd/modules.vhd may be missing (microsoft/WSL #40616 class). See the wsl-recovery runbook before trusting this machine.','WSL RESILIENCE ALERT','OK','Error') }"
$logonArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$logonCmd`""
$logonAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $logonArgs
# Scope the logon trigger to the current user — a bare -AtLogOn is an "any user"
# (machine-wide) trigger that requires elevation; per-user does not.
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logonSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
if ($PSCmdlet.ShouldProcess('WSL Integrity Check', 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName 'WSL Integrity Check' -Action $logonAction -Trigger $logonTrigger `
        -Settings $logonSettings -Description 'At-logon WSL platform integrity check; alerts if broken (OverSteward WSL resilience).' -Force | Out-Null
    Write-Host "Registered 'WSL Integrity Check' (at logon)." -ForegroundColor Green
}

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskName 'WSL *'" -ForegroundColor Cyan
Write-Host "Run a backup now to validate + measure size:  powershell -File `"$backupPath`""
Write-Host "Backup log + last-success marker:  $InstallDir\backup.log, $InstallDir\export.last-ok"
Write-Host "Uninstall:  Unregister-ScheduledTask -TaskName 'WSL Monthly Backup','WSL Integrity Check' -Confirm:`$false"
