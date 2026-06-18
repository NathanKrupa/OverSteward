# ABOUTME: Routine WSL data backup - dated `wsl --export` to a non-C: drive with retention pruning.
# ABOUTME: Turns a future platform wipe from a crisis into a ~5-minute `wsl --import`.
#requires -Version 5

<#
.SYNOPSIS
  Export a WSL distro to a dated archive on E: and prune to a retention count.

.DESCRIPTION
  User data lives in ext4.vhdx, independent of the WSL app binaries - it survived
  the 2026-06-17 wipe only by luck (there was no backup). This script makes that
  survival deliberate. It exports the distro to E:\WSLBackups\<distro>_<date>.tar
  (E: is a separate physical drive from C:, so a C: failure does not take the
  backups with it), verifies the archive is non-empty, and keeps the newest
  -Keep copies.

  `wsl --export` briefly stops the distro to take a consistent snapshot.

  Recovery is the inverse:
    wsl --import <NewName> <InstallDir> E:\WSLBackups\<distro>_<date>.tar

.PARAMETER Distro
  Distro to export. Default: Ubuntu-24.04.

.PARAMETER Dest
  Backup directory. Default: E:\WSLBackups (the "Dagger" drive, 393 GB free).

.PARAMETER Keep
  How many most-recent archives to retain. Older ones are pruned. Default: 3.
  Tune after the first run reveals the real archive size (Get-ChildItem $Dest).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Backup-Wsl.ps1
#>
[CmdletBinding()]
param(
    [string]$Distro = 'Ubuntu-24.04',
    [string]$Dest = 'E:\WSLBackups',
    [int]$Keep = 3
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyy-MM-dd'
$file = Join-Path $Dest ("{0}_{1}.tar" -f $Distro, $stamp)

if (Test-Path -LiteralPath $file) {
    Write-Host "Today's backup already exists ($file); overwriting."
    Remove-Item -LiteralPath $file -Force
}

Write-Host "Exporting $Distro -> $file (the distro stops briefly for a clean snapshot) ..."
& wsl.exe --export $Distro $file
if ($LASTEXITCODE -ne 0) {
    throw "wsl --export failed with exit code $LASTEXITCODE"
}

$item = Get-Item -LiteralPath $file
if ($item.Length -eq 0) {
    Remove-Item -LiteralPath $file -Force
    throw 'Export produced a zero-byte archive; removed it. Backup FAILED.'
}
Write-Host ("Backup OK: {0}  ({1:N1} GB)" -f $file, ($item.Length / 1GB)) -ForegroundColor Green

# Retention: keep the newest $Keep archives for this distro, prune the rest.
$pattern = "{0}_*.tar" -f $Distro
$archives = Get-ChildItem -LiteralPath $Dest -Filter $pattern | Sort-Object LastWriteTime -Descending
if ($archives.Count -gt $Keep) {
    foreach ($old in ($archives | Select-Object -Skip $Keep)) {
        Write-Host "Pruning old backup: $($old.Name)"
        Remove-Item -LiteralPath $old.FullName -Force
    }
}

# Report current footprint so retention can be tuned against E: free space.
$total = (Get-ChildItem -LiteralPath $Dest -Filter $pattern | Measure-Object Length -Sum).Sum
Write-Host ("Retained {0} archive(s), {1:N1} GB total in {2}." -f `
    (Get-ChildItem -LiteralPath $Dest -Filter $pattern).Count, ($total / 1GB), $Dest)
