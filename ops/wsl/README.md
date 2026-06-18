ABOUTME: Overview + usage for the WSL resilience scripts (PowerShell, Windows-side).
ABOUTME: Canonical source lives here in OverSteward; Install-WslResilience.ps1 deploys to a Windows path.

# WSL Resilience (`ops/wsl/`)

PowerShell tooling so a WSL **app** update can never silently wipe the Linux
environment again (origin: microsoft/WSL #40616, 2026-06-17). Full failure
signature, recovery paths, and policy: [`documentation/runbooks/wsl-recovery.md`](../../documentation/runbooks/wsl-recovery.md).

These are **Windows-side** scripts. This repo (in WSL) is the canonical source;
`Install-WslResilience.ps1` copies them to a Windows-native folder so Task
Scheduler can run them even when WSL itself is broken.

## Division of labor

- **Built in-repo (safe, version-controlled):** all five scripts + the runbook.
- **You run on Windows (system-touching — review first):**
  `Install-WslResilience.ps1` (registers scheduled tasks) and, optionally,
  `Set-WslUpdatePolicy.ps1 -Apply` (elevated; writes a Store policy key).
  Nothing here runs automatically until you install it.

## The scripts

| Script | What it does | Who runs it |
|---|---|---|
| `Test-WslIntegrity.ps1` | The gate: `system.vhd` + `modules.vhd` present/non-empty and `wsl -l -v` responds. Exit 0/1. Read-only, safe to run anytime. | auto (logon task) + you |
| `Update-WslSafely.ps1` | Run **instead of** `wsl --update`: snapshot → update → gate → auto `--rollback` on failure. | you, monthly |
| `Backup-Wsl.ps1` | Dated `wsl --export` to `E:\WSLBackups`, keep newest 3. | auto (weekly task) + you |
| `Set-WslUpdatePolicy.ps1` | Reports update-control state; `-Apply` (elevated) disables Store auto-download. Best-effort. | you, once |
| `Install-WslResilience.ps1` | Deploys the scripts to `%LOCALAPPDATA%\WslResilience` and registers the weekly-backup + logon-integrity tasks. | you, once |

## Quick start (from Windows PowerShell, with WSL running so this path resolves)

```powershell
cd \\wsl.localhost\Ubuntu-24.04\home\natha\OverSteward\ops\wsl   # (after merge to master)

# 1. See current state, no changes:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-WslIntegrity.ps1

# 2. Install the scheduled tasks (weekly backup + logon integrity check):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1

# 3. Run a backup now to validate the path and measure real archive size:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Backup-Wsl.ps1

# 4. (optional, elevated) reduce silent Store updates:
#    Start an elevated PowerShell, then:
#    .\Set-WslUpdatePolicy.ps1 -Apply
```

From then on: backups run weekly, the integrity gate alerts at logon if a future
update breaks the platform, and you update monthly via `Update-WslSafely.ps1`.

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName 'WSL Weekly Backup','WSL Integrity Check' -Confirm:$false
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\WslResilience"
# and, if you set it, revert the Store policy key (value 4 or delete it).
```
