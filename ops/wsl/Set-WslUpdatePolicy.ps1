# ABOUTME: Best-effort control of unattended WSL app updates on Windows 11 Home (no gpedit).
# ABOUTME: Reports current state; with -Apply, sets the Store auto-download policy key. Honest about limits.
#requires -Version 5

<#
.SYNOPSIS
  Reduce the chance of an unattended WSL app update, and report what can and
  cannot be controlled on Windows 11 Home.

.DESCRIPTION
  HONEST FRAMING: you cannot fully stop WSL from updating itself - this is a
  known, unresolved complaint (microsoft/WSL #10799, discussion #12675), and on
  Windows 11 Home there is no Group Policy (gpedit) to lean on. So this is one
  layer of defense-in-depth, NOT a guarantee. The real protection is:
    - Update-WslSafely.ps1  (verify + auto-rollback)
    - Backup-Wsl.ps1        (fast, data-safe recovery)
    - the recovery runbook.

  What this script can do:
    - Report whether the Microsoft Store auto-download policy is set.
    - With -Apply (elevated), set
      HKLM:\SOFTWARE\Policies\Microsoft\WindowsStore\AutoDownload = 2
      which disables automatic app updates store-wide. Trade-off: ALL Store
      apps then require manual updates, and the WSL app is updated on your
      schedule via Update-WslSafely.ps1.

  Manual levers this script only documents (cannot reliably script on Home):
    - Settings > Windows Update > Pause updates (max 5 weeks; renew as needed).
    - Microsoft Store > Settings > "App updates" toggle (per-user UI).

.PARAMETER Apply
  Actually write the Store AutoDownload policy key. Requires an elevated shell.
  Without it, the script only reports.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Set-WslUpdatePolicy.ps1
  # report only

.EXAMPLE
  # elevated:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Set-WslUpdatePolicy.ps1 -Apply
#>
[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'

$key = 'HKLM:\SOFTWARE\Policies\Microsoft\WindowsStore'
$name = 'AutoDownload'

Write-Host '=== Current Store auto-update policy ===' -ForegroundColor Cyan
$current = (Get-ItemProperty -Path $key -Name $name -ErrorAction SilentlyContinue).$name
if ($null -eq $current) {
    Write-Host "  $key\$name : (not set - Store auto-updates are at their default = ON)"
}
else {
    $meaning = if ($current -eq 2) { 'disabled (manual updates)' } elseif ($current -eq 4) { 'enabled' } else { "value $current" }
    Write-Host "  $key\$name = $current  ($meaning)"
}

if (-not $Apply) {
    Write-Host "`nReport only. Re-run elevated with -Apply to set AutoDownload=2 (disable Store auto-updates)." -ForegroundColor Yellow
    Write-Host 'Manual levers (do these by hand):' -ForegroundColor Yellow
    Write-Host '  - Settings > Windows Update > Pause updates (renew within 5 weeks).'
    Write-Host '  - Microsoft Store > profile > Settings > turn OFF "App updates".'
    Write-Host "`nReminder: prevention is best-effort. The integrity gate + backups are the real safety net."
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error 'Run from an ELEVATED PowerShell to use -Apply (writes to HKLM).'
    exit 1
}

if (-not (Test-Path -LiteralPath $key)) {
    New-Item -Path $key -Force | Out-Null
}
Set-ItemProperty -Path $key -Name $name -Type DWord -Value 2
Write-Host "Set $key\$name = 2 (Store auto-updates disabled)." -ForegroundColor Green
Write-Host 'WSL will now update only when you run Update-WslSafely.ps1. Revert with value 4 or by deleting the key.'
