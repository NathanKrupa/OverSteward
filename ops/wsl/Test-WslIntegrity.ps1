# ABOUTME: WSL platform integrity gate - verify the VM-platform VHD files exist and WSL responds.
# ABOUTME: Exit 0 = healthy, 1 = broken. The keystone of the WSL resilience process (microsoft/WSL #40616).
#requires -Version 5

<#
.SYNOPSIS
  Prove the WSL runtime is intact: the VM-platform VHD files are present and
  non-empty, and `wsl -l -v` returns successfully.

.DESCRIPTION
  The 2.7.x regression (microsoft/WSL #40616 / #40488) could leave
  C:\Program Files\WSL\system.vhd and tools\modules.vhd missing after an
  interrupted update, breaking EVERY distro with
  Wsl/Service/CreateInstance/CreateVm/HCS/ERROR_FILE_NOT_FOUND (and taking
  Docker Desktop down with it). This gate catches that state before the
  environment is trusted or an update is declared successful.

.OUTPUTS
  Exit code 0 (healthy) or 1 (broken). Use -Quiet for scheduled/automated runs.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-WslIntegrity.ps1
#>
[CmdletBinding()]
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'

$wslDir = Join-Path $env:ProgramFiles 'WSL'
$required = @(
    (Join-Path $wslDir 'system.vhd'),
    (Join-Path $wslDir 'tools\modules.vhd')
)

$problems = @()

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

if ($problems.Count -eq 0) {
    if (-not $Quiet) {
        Write-Host 'WSL integrity OK - VHD files present and non-empty, WSL responds.' -ForegroundColor Green
    }
    exit 0
}

Write-Warning 'WSL INTEGRITY CHECK FAILED:'
foreach ($p in $problems) { Write-Warning "  - $p" }
Write-Warning 'See documentation/runbooks/wsl-recovery.md before trusting this environment.'
exit 1
