# ABOUTME: Due- and readiness-gated WSL backup - dated `wsl --export` to a non-C: drive when due and idle.
# ABOUTME: Not due exits 0; busy logs the blocker and exits 3; FAILED or >35 days overdue raises a dialog.
#requires -Version 5

<#
.SYNOPSIS
  Export a WSL distro to a dated archive on E: - when an export is due and the
  distro is idle.

.DESCRIPTION
  User data lives in ext4.vhdx, independent of the WSL app binaries - it survived
  the 2026-06-17 wipe only by luck (there was no backup). This script makes that
  survival deliberate: it exports the distro to E:\WSLBackups\<distro>_<date>.tar
  (E: is a separate physical drive from C:, so a C: failure does not take the
  backups with it), verifies the archive is non-empty, and keeps the newest
  -Keep copies.

  DUE: the scheduled task runs every night (01:17, repeating hourly to ~06:17),
  but an export is due only when the last success, the date in export.last-ok,
  is 28 days old or more, or the marker is absent or unreadable. A run that is
  not due exits 0 at once without touching WSL or the log. So a skipped or
  failed attempt is retried the next night, and every night after, until one
  succeeds.

  `wsl --export` terminates every process in the distro to take its snapshot -
  Claude sessions, drains, crawls, compose. So before exporting, this asks the
  distro whether it is idle, by running OverSteward's readiness check:

    wsl.exe -d <Distro> -- /home/natha/OverSteward/.venv/bin/python /home/natha/OverSteward/scripts/backup_ready.py

  It runs from the primary checkout by default, never a session worktree, and
  needs that checkout to have pulled the readiness service; until it has, every
  attempt is could-not-look. Only a readiness exit 0 lets the export run. Busy
  (exit 1 with a BUSY verdict), could-not-look (2, or exit 1 without a BUSY
  verdict, such as a Python traceback), or a wsl.exe that fails or cannot start:
  the blocker is logged to backup.log in -StateDir, nothing is exported, nothing
  is pruned, and the script exits 3. The scheduled task retries hourly instead.

  The probes see four kinds of work: working Claude Code sessions (an open but
  idle session is not work - its conversation is on disk and resumes), detached
  GrantSpider long runs (grantspider, supervisor.sh), running estate job
  services, and running docker containers. Other work - an arbitrary nohup or
  tmux job - is not detected, and the export would kill it.

  A successful export writes today's date to export.last-ok in -StateDir, which
  makes every later run not due for 28 days.

  A failed export removes its partial archive, is logged as FAILED (distinct
  from SKIPPED), and exits 1.

  ALERT: on a FAILED export, and on a skip when the last success is more than
  35 days old (or there has never been one), a Windows dialog names the last
  success date and the latest SKIPPED/FAILED entry from backup.log. It is shown
  at most once per calendar day (the date in alert.last-shown in -StateDir),
  and launched as a separate process, so the run and its retries never wait on
  it.

  Exit codes:
    0  exported OK, or not due
    1  the export itself failed (thrown error)
    3  skipped - the distro was busy, or readiness could not look

  Recovery is the inverse:
    wsl --import <NewName> <InstallDir> E:\WSLBackups\<distro>_<date>.tar

.PARAMETER Distro
  Distro to export. Default: Ubuntu-24.04.

.PARAMETER Dest
  Backup directory. Default: E:\WSLBackups (the "Dagger" drive).

.PARAMETER Keep
  How many most-recent archives to retain. Older ones are pruned after a good
  export. Default: 1. Measured 2026-10-11: one export is ~131 GB, and E: is
  shared, so a second copy is not affordable. The daily restic backup (OS#582)
  carries the history; this export is the whole-distro rebuild point.

.PARAMETER ReadinessPython
  Linux path of the interpreter that runs the readiness check. Default: the
  primary checkout's /home/natha/OverSteward/.venv/bin/python.

.PARAMETER ReadinessScript
  Linux path of the readiness check. Default: the primary checkout's
  /home/natha/OverSteward/scripts/backup_ready.py.

.PARAMETER StateDir
  Where backup.log, the export.last-ok marker and the alert.last-shown marker
  live. Default: the install dir, %LOCALAPPDATA%\WslResilience.

.PARAMETER DueDays
  An export is due when the last success is at least this many days old.
  Default: 28.

.PARAMETER OverdueDays
  A skip raises the alert when the last success is more than this many days
  old. Default: 35.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Backup-Wsl.ps1
#>
[CmdletBinding()]
param(
    [string]$Distro = 'Ubuntu-24.04',
    [string]$Dest = 'E:\WSLBackups',
    [int]$Keep = 1,
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'WslResilience'),
    # The readiness check, from the primary checkout - never a session worktree.
    [string]$ReadinessPython = '/home/natha/OverSteward/.venv/bin/python',
    [string]$ReadinessScript = '/home/natha/OverSteward/scripts/backup_ready.py',
    [int]$DueDays = 28,
    [int]$OverdueDays = 35
)

$ErrorActionPreference = 'Stop'
# wsl.exe writes its own messages as UTF-16 unless asked for UTF-8; the log must read.
$env:WSL_UTF8 = '1'

if (-not (Test-Path -LiteralPath $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}
$logFile = Join-Path $StateDir 'backup.log'
$marker = Join-Path $StateDir 'export.last-ok'
$alertMarker = Join-Path $StateDir 'alert.last-shown'

function Write-BackupLog([string]$message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -LiteralPath $logFile -Value $line
    Write-Host $line
}

$stamp = Get-Date -Format 'yyyy-MM-dd'

# The last successful export, or $null when the marker is absent or unreadable.
# A date in the future (a clock that once ran fast) is unreadable too: trusting
# it would make every night "not due" with nothing to say so.
$lastOk = $null
$lastOkText = 'never'
if (Test-Path -LiteralPath $marker) {
    $parsed = [datetime]::MinValue
    $text = "$(Get-Content -LiteralPath $marker -Raw)".Trim()
    if (-not [datetime]::TryParseExact($text, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
        $lastOkText = "unreadable ('$text')"
    } elseif ($parsed -gt (Get-Date).Date) {
        $lastOkText = "unreadable ('$text' is in the future)"
    } else {
        $lastOk = $parsed
        $lastOkText = $lastOk.ToString('yyyy-MM-dd')
    }
}
$ageDays = if ($null -eq $lastOk) { $null } else { ((Get-Date).Date - $lastOk).Days }

function Send-BackupAlert([string]$why) {
    # At most once per calendar day; launched detached so no run waits on the dialog.
    if ((Test-Path -LiteralPath $alertMarker) -and
        ("$(Get-Content -LiteralPath $alertMarker -Raw)".Trim() -eq $stamp)) {
        Write-BackupLog "Alert already shown today; not repeating it."
        return
    }
    $lines = @(Get-Content -LiteralPath $logFile)
    $latest = '(no SKIPPED or FAILED entry in backup.log)'
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match '  (SKIPPED|FAILED) - ') {
            $end = [Math]::Min($lines.Count - 1, $i + 8)
            $latest = ($lines[$i..$end] | ForEach-Object {
                if ($_.Length -gt 220) { $_.Substring(0, 220) + '...' } else { $_ } }) -join "`n"
            break
        }
    }
    $text = "WSL backup: $why`n`nLast successful export: $lastOkText`n`n" +
        "Latest from backup.log:`n$latest`n`nLog: $logFile"
    $command = 'Add-Type -AssemblyName PresentationFramework; ' +
        "[void][System.Windows.MessageBox]::Show('$($text.Replace("'", "''"))'," +
        "'WSL BACKUP ALERT','OK','Warning')"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    try {
        Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
            -ArgumentList @('-NoProfile', '-EncodedCommand', $encoded)
    } catch {
        Write-BackupLog "ALERT could not be shown: $_"
        return
    }
    Set-Content -LiteralPath $alertMarker -Value $stamp -Encoding ASCII
    Write-BackupLog "ALERT raised: $why (last success: $lastOkText)."
}

# 1. Not due: a recent success makes every run a no-op until $DueDays have passed.
if ($null -ne $ageDays -and $ageDays -lt $DueDays) {
    Write-Host "Not due: last export $lastOkText, $ageDays day(s) ago; due at $DueDays days."
    exit 0
}

# 2. Ask the distro whether it is idle. Native stderr under 'Stop' would throw
#    on the first line, so capture with 'Continue' and judge by the exit code.
$readyCode = $null
$readyOutput = ''
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    $readyOutput = (& wsl.exe -d $Distro -- $ReadinessPython $ReadinessScript 2>&1 |
        ForEach-Object { "$_" }) -join "`n"
    $readyCode = $LASTEXITCODE
} catch {
    $readyOutput = "wsl.exe could not be started: $_"
} finally {
    $ErrorActionPreference = $previousPreference
}

if ($readyCode -ne 0) {
    # Python's own traceback also exits 1, so busy needs the BUSY headline too.
    if ($readyCode -eq 1 -and $readyOutput.TrimStart().StartsWith('BUSY')) {
        $label = 'busy'
    } elseif ($readyCode -eq 1 -or $readyCode -eq 2) {
        $label = 'could not look'
    } else {
        $label = 'could not look (wsl.exe failed)'
    }
    $codeText = if ($null -eq $readyCode) { 'none' } else { "$readyCode" }
    Write-BackupLog "SKIPPED - $label (readiness exit $codeText); nothing exported, nothing pruned."
    foreach ($line in ($readyOutput -split "`n")) {
        if ($line.Trim()) { Write-BackupLog "  $line" }
    }
    if ($null -eq $ageDays -or $ageDays -gt $OverdueDays) {
        $overdue = if ($null -eq $ageDays) { 'no successful export on record' } else {
            "no successful export for $ageDays days" }
        Send-BackupAlert "$overdue; tonight's attempt was skipped ($label)."
    }
    exit 3
}

# 3. Idle: export. Every failure from here to the marker is FAILED and alerts.
$file = Join-Path $Dest ("{0}_{1}.tar" -f $Distro, $stamp)
$failure = $null
try {
    if (-not (Test-Path -LiteralPath $Dest)) {
        New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    }
    if (Test-Path -LiteralPath $file) {
        Write-BackupLog "A partial archive from today exists ($file); overwriting."
        Remove-Item -LiteralPath $file -Force
    }
} catch {
    $failure = "could not prepare the export: $_"
}

if ($null -eq $failure) {
    Write-BackupLog "Readiness: ready (last success: $lastOkText). Exporting $Distro -> $file ..."
    try {
        & wsl.exe --export $Distro $file
        if ($LASTEXITCODE -ne 0) { $failure = "wsl --export exited $LASTEXITCODE" }
    } catch {
        $failure = "wsl --export could not run: $_"
    }
}
if ($null -eq $failure -and (Get-Item -LiteralPath $file -ErrorAction SilentlyContinue).Length -gt 0) {
    $item = Get-Item -LiteralPath $file
} elseif ($null -eq $failure) {
    $failure = 'export produced a missing or zero-byte archive'
}
if ($null -ne $failure) {
    # A partial archive is not a backup, and at this size it crowds out the next one.
    $cleanup = 'removed any partial archive'
    try {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    } catch {
        $cleanup = "could NOT remove the partial archive $file ($_)"
    }
    Write-BackupLog "FAILED - $failure; $cleanup."
    Send-BackupAlert "the export FAILED ($failure)."
    throw "Backup FAILED: $failure"
}
Set-Content -LiteralPath $marker -Value $stamp -Encoding ASCII
Write-BackupLog ("Backup OK: {0}  ({1:N1} GB)" -f $file, ($item.Length / 1GB))

# 4. Retention: keep the newest $Keep archives for this distro, prune the rest.
$pattern = "{0}_*.tar" -f $Distro
$archives = @(Get-ChildItem -LiteralPath $Dest -Filter $pattern | Sort-Object LastWriteTime -Descending)
if ($archives.Count -gt $Keep) {
    foreach ($old in ($archives | Select-Object -Skip $Keep)) {
        Write-BackupLog "Pruning old backup: $($old.Name)"
        Remove-Item -LiteralPath $old.FullName -Force
    }
}

# Report current footprint so retention can be tuned against E: free space.
$retained = @(Get-ChildItem -LiteralPath $Dest -Filter $pattern)
$total = ($retained | Measure-Object Length -Sum).Sum
Write-BackupLog ("Retained {0} archive(s), {1:N1} GB total in {2}." -f $retained.Count, ($total / 1GB), $Dest)
exit 0
