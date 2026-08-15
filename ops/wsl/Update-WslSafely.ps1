# ABOUTME: Safe WSL update wrapper - update, verify integrity, auto-rollback if the update broke the platform.
# ABOUTME: Run this INSTEAD of a bare `wsl --update`. Defends against the #40616 silent-breakage class.
#requires -Version 5

<#
.SYNOPSIS
  Update WSL deliberately and safely: snapshot the version, run the update, run
  the integrity gate, and roll back automatically if the update left the
  platform broken.

.DESCRIPTION
  Bare `wsl --update` is the exact action that broke this machine on 2026-06-17.
  This wrapper makes updating a verified, reversible operation:
    1. Record the current `wsl --version`.
    2. Remind the operator that a recent backup is the real safety net.
    3. Run `wsl --update`.
    4. Run Test-WslIntegrity.ps1.
    5. On failure -> `wsl --update --rollback`, then re-verify.

  Exit codes: 0 healthy after update; 2 rolled back to a healthy prior version
  (do not re-update until the regression is confirmed fixed); 3 still broken
  after rollback (follow the recovery runbook).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Update-WslSafely.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$gate = Join-Path $here 'Test-WslIntegrity.ps1'

function Invoke-Gate {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $gate
    return $LASTEXITCODE
}

Write-Host '=== Current WSL version (pre-update) ===' -ForegroundColor Cyan
& wsl.exe --version

Write-Warning 'A recent `Backup-Wsl.ps1` export is your real safety net. If you are not sure one exists, stop and run it first.'
$answer = Read-Host 'Proceed with wsl --update? (yes/no)'
if ($answer -ne 'yes') {
    Write-Host 'Aborted by operator. Nothing changed.'
    exit 0
}

Write-Host "`n=== Running wsl --update ===" -ForegroundColor Cyan
& wsl.exe --update

Write-Host "`n=== Verifying integrity ===" -ForegroundColor Cyan
if ((Invoke-Gate) -eq 0) {
    Write-Host "`nUpdate verified healthy." -ForegroundColor Green
    & wsl.exe --version
    exit 0
}

Write-Warning 'Integrity gate FAILED after update - rolling back with `wsl --update --rollback`.'
& wsl.exe --update --rollback

Write-Host "`n=== Re-verifying after rollback ===" -ForegroundColor Cyan
if ((Invoke-Gate) -eq 0) {
    Write-Warning 'Rolled back to the previous version; environment is healthy again.'
    Write-Warning 'Do NOT re-update until #40616-class regressions are confirmed fixed in the target build.'
    exit 2
}

Write-Error 'STILL BROKEN after rollback. Follow documentation/runbooks/wsl-recovery.md (installer repair, or reinstall + `wsl --import` from your latest E:\WSLBackups export).'
exit 3
