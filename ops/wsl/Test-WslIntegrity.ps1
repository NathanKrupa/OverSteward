# ABOUTME: WSL integrity gate - the VM-platform VHDs exist, WSL responds, and both backups are current.
# ABOUTME: Exit 0 = healthy, 1 = broken. Reads only C: and the export drive, so it alerts with WSL dead.
#requires -Version 5

<#
.SYNOPSIS
  Prove the WSL runtime is intact and recoverable: the VM-platform VHD files
  are present and non-empty, `wsl -l -v` returns successfully, the daily
  restic backup verified a restore within the last 48 hours, and the newest
  full export is no more than 45 days old.

.DESCRIPTION
  The 2.7.x regression (microsoft/WSL #40616 / #40488) could leave
  C:\Program Files\WSL\system.vhd and tools\modules.vhd missing after an
  interrupted update, breaking EVERY distro with
  Wsl/Service/CreateInstance/CreateVm/HCS/ERROR_FILE_NOT_FOUND (and taking
  Docker Desktop down with it). This gate catches that state before the
  environment is trusted or an update is declared successful.

  It is also the logon canary for the backups. The in-distro health sweep
  (scripts/backup_health.py) cannot run while the distro is dead, so this gate
  reads the same two facts from Windows paths:
    - RESTIC: restic.last-ok in -StateDir, the C: mirror the daily home backup
      writes after a verified restore. Its first token is a naive local
      timestamp, yyyy-MM-ddTHH:mm:ss. Absent, unparseable, dated in the future
      or older than -ResticMaxHours fails.
    - EXPORT: the newest <Distro>_YYYY-MM-DD.tar in -BackupDest, chosen by the
      date in its name. None, zero bytes, older than -ExportMaxDays, or the
      destination unreachable fails.
  The thresholds equal the sweep's (tests/backup/test_test_wsl_integrity_ps1.py
  pins the parity). -PlatformOnly skips both, for Update-WslSafely.ps1: a stale
  backup must not roll back a healthy update.

.OUTPUTS
  Exit code 0 (healthy) or 1 (broken), with each problem named in a warning.
  Use -Quiet for scheduled/automated runs.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-WslIntegrity.ps1
#>
[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$PlatformOnly,
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'WslResilience'),
    [string]$BackupDest = 'E:\WSLBackups',
    [string]$Distro = 'Ubuntu-24.04',
    [int]$ResticMaxHours = 48,
    [int]$ExportMaxDays = 45
)

$ErrorActionPreference = 'Stop'
$invariant = [Globalization.CultureInfo]::InvariantCulture

function Get-ResticProblem {
    $marker = Join-Path $StateDir 'restic.last-ok'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        return "RESTIC: no verified backup on record - $marker absent"
    }
    try {
        $text = [IO.File]::ReadAllText($marker)
    }
    catch {
        return "RESTIC: $marker unreadable: $($_.Exception.Message)"
    }
    $token = ($text.Trim() -split '\s+')[0]
    $stamp = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($token, 'yyyy-MM-dd\THH:mm:ss', $invariant,
            [Globalization.DateTimeStyles]::AssumeLocal, [ref]$stamp)) {
        return "RESTIC: $marker unparseable: '$token'"
    }
    # Compare in UTC so a DST change between the backup and now is not an hour of drift.
    $hours = ([datetime]::UtcNow - $stamp.ToUniversalTime()).TotalHours
    if ($hours -lt 0) {
        return "RESTIC: $marker is dated in the future ($token)"
    }
    if ($hours -gt $ResticMaxHours) {
        return ('RESTIC: last verified backup {0:N1} h ago, at {1} (limit {2} h)' -f $hours, $token, $ResticMaxHours)
    }
    $script:measured += ('restic verified {0:N1} h ago' -f $hours)
}

function Get-ExportProblem {
    if (-not (Test-Path -LiteralPath $BackupDest -PathType Container)) {
        return "EXPORT: backup destination $BackupDest unreachable"
    }
    $pattern = '^' + [regex]::Escape($Distro) + '_(\d{4}-\d{2}-\d{2})\.tar$'
    $newest = $null
    $newestDay = [datetime]::MinValue
    try {
        $files = @(Get-ChildItem -LiteralPath $BackupDest -File)
    }
    catch {
        return "EXPORT: $BackupDest could not be read: $($_.Exception.Message)"
    }
    foreach ($f in $files) {
        if ($f.Name -cnotmatch $pattern) { continue }
        $day = [datetime]::MinValue
        if ([datetime]::TryParseExact($Matches[1], 'yyyy-MM-dd', $invariant,
                [Globalization.DateTimeStyles]::None, [ref]$day) -and
            ($null -eq $newest -or $day -gt $newestDay)) {
            $newest = $f
            $newestDay = $day
        }
    }
    if ($null -eq $newest) {
        return "EXPORT: no ${Distro}_YYYY-MM-DD.tar in $BackupDest"
    }
    if ($newest.Length -eq 0) {
        return "EXPORT: newest archive $($newest.FullName) is zero bytes"
    }
    $days = ((Get-Date).Date - $newestDay).Days
    if ($days -gt $ExportMaxDays) {
        return "EXPORT: newest archive $($newest.Name) is $days days old (limit $ExportMaxDays days)"
    }
    $script:measured += "export $($newest.Name) $days days old"
}

$wslDir = Join-Path $env:ProgramFiles 'WSL'
$required = @(
    (Join-Path $wslDir 'system.vhd'),
    (Join-Path $wslDir 'tools\modules.vhd')
)

$problems = @()
$measured = @('VHD files present and non-empty', 'WSL responds')

foreach ($f in $required) {
    if (-not (Test-Path -LiteralPath $f)) {
        $problems += "MISSING: $f"
    }
    elseif ((Get-Item -LiteralPath $f).Length -eq 0) {
        $problems += "ZERO-LENGTH: $f"
    }
}

# WSL must actually respond - a present-but-unmountable platform still fails here.
try {
    $null = & wsl.exe -l -v 2>&1
    if ($LASTEXITCODE -ne 0) {
        $problems += "wsl -l -v exited with code $LASTEXITCODE"
    }
}
catch {
    $problems += "wsl -l -v threw: $($_.Exception.Message)"
}

if ($PlatformOnly) {
    $measured += 'backup checks skipped (-PlatformOnly)'
}
else {
    $problems += @(Get-ResticProblem)
    $problems += @(Get-ExportProblem)
}

if ($problems.Count -eq 0) {
    if (-not $Quiet) {
        Write-Host ('WSL integrity OK - ' + ($measured -join '; ') + '.') -ForegroundColor Green
    }
    exit 0
}

Write-Warning 'WSL INTEGRITY CHECK FAILED:'
foreach ($p in $problems) { Write-Warning "  - $p" }
Write-Warning 'See documentation/runbooks/wsl-recovery.md before trusting this environment (VHD or WSL problems: section 3; RESTIC or EXPORT: section 4).'
exit 1
