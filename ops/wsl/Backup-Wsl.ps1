# ABOUTME: Readiness-gated WSL backup - dated `wsl --export` to a non-C: drive, only when nothing is running.
# ABOUTME: Asks scripts/backup_ready.py first; busy or could-not-look means log the blocker, exit 3, export nothing.
#requires -Version 5

<#
.SYNOPSIS
  Export a WSL distro to a dated archive on E: - but only when the distro is idle.

.DESCRIPTION
  User data lives in ext4.vhdx, independent of the WSL app binaries - it survived
  the 2026-06-17 wipe only by luck (there was no backup). This script makes that
  survival deliberate: it exports the distro to E:\WSLBackups\<distro>_<date>.tar
  (E: is a separate physical drive from C:, so a C: failure does not take the
  backups with it), verifies the archive is non-empty, and keeps the newest
  -Keep copies.

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

  The probes see four kinds of work: Claude Code sessions, detached GrantSpider
  long runs (grantspider, supervisor.sh), running estate job services, and
  running docker containers. Other work - an arbitrary nohup or tmux job - is
  not detected, and the export would kill it.

  A successful export writes today's date to export.last-ok in -StateDir. A run
  that finds today's date already there exits 0 at once, so the hourly retries
  stop after the first success of the day.

  Exit codes:
    0  exported OK, or already exported today
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
  Where backup.log and the export.last-ok marker live. Default: the install dir,
  %LOCALAPPDATA%\WslResilience.

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
    [string]$ReadinessScript = '/home/natha/OverSteward/scripts/backup_ready.py'
)

$ErrorActionPreference = 'Stop'
# wsl.exe writes its own messages as UTF-16 unless asked for UTF-8; the log must read.
$env:WSL_UTF8 = '1'

if (-not (Test-Path -LiteralPath $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}
$logFile = Join-Path $StateDir 'backup.log'
$marker = Join-Path $StateDir 'export.last-ok'

function Write-BackupLog([string]$message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -LiteralPath $logFile -Value $line
    Write-Host $line
}

$stamp = Get-Date -Format 'yyyy-MM-dd'

# 1. Already exported today: the hourly retries stop here.
if ((Test-Path -LiteralPath $marker) -and
    ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $stamp)) {
    Write-BackupLog "Already exported today ($stamp); nothing to do."
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
    exit 3
}

# 3. Idle: export.
if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}
$file = Join-Path $Dest ("{0}_{1}.tar" -f $Distro, $stamp)

if (Test-Path -LiteralPath $file) {
    Write-BackupLog "A partial archive from today exists ($file); overwriting."
    Remove-Item -LiteralPath $file -Force
}

Write-BackupLog "Readiness: ready. Exporting $Distro -> $file ..."
& wsl.exe --export $Distro $file
$exportCode = $LASTEXITCODE
if ($exportCode -ne 0) {
    # A partial archive is not a backup, and at this size it crowds out the next one.
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    Write-BackupLog "FAILED - wsl --export exited $exportCode; removed any partial archive."
    throw "wsl --export failed with exit code $exportCode"
}

$item = Get-Item -LiteralPath $file
if ($item.Length -eq 0) {
    Remove-Item -LiteralPath $file -Force
    Write-BackupLog 'FAILED - export produced a zero-byte archive; removed it.'
    throw 'Export produced a zero-byte archive; removed it. Backup FAILED.'
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
