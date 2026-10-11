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
| `Backup-Wsl.ps1` | Dated `wsl --export` to `E:\WSLBackups`, keep newest 1 (~131 GB). Asks `scripts/backup_ready.py` first and exports only when the distro is idle; busy or could-not-look logs the blocker to `backup.log` and exits 3. Never runs over a Claude session, estate job or container. | auto (monthly task) + you |
| `Set-WslUpdatePolicy.ps1` | Reports update-control state; `-Apply` (elevated) disables Store auto-download. Best-effort. | you, once |
| `Install-WslResilience.ps1` | Deploys the scripts to `%LOCALAPPDATA%\WslResilience` and registers the monthly-backup + logon-integrity tasks (and removes the retired `'WSL Weekly Backup'` task). | you, once; again after any script change |

## Quick start (from Windows PowerShell, with WSL running so this path resolves)

```powershell
cd \\wsl.localhost\Ubuntu-24.04\home\natha\OverSteward\ops\wsl   # (after merge to master)

# 1. See current state, no changes:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-WslIntegrity.ps1

# 2. Install the scheduled tasks (monthly backup + logon integrity check):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1

# 3. Run a backup now to validate the path and measure real archive size.
#    It exports only if nothing is running in the distro (exit 3 otherwise -
#    see %LOCALAPPDATA%\WslResilience\backup.log for what blocked it):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Backup-Wsl.ps1

# 4. (optional, elevated) reduce silent Store updates:
#    Start an elevated PowerShell, then:
#    .\Set-WslUpdatePolicy.ps1 -Apply
```

From then on: the full export is attempted on the first Sunday of each month,
the integrity gate alerts at logon if a future update breaks the platform, and
you update monthly via `Update-WslSafely.ps1`.

## The monthly export: skip if busy, never kill what it can see

`wsl --export` terminates every process in the distro to take its snapshot, so
the backup refuses to run over work in progress:

- **When:** first Sunday of the month at 05:17 (after the 03:30 dream cycle),
  retried every hour for 17 hours (to ~22:17).
- **Gate:** each attempt first runs, inside the distro,
  `/home/natha/OverSteward/.venv/bin/python /home/natha/OverSteward/scripts/backup_ready.py`
  (always the primary checkout). It exits 0 ready, 1 busy (a Claude Code
  session, a running estate job service such as `dream-cycle.service`, or a
  running docker container, each named), or 2 could not look (a probe failed).
- **Only 0 exports.** On 1, 2, or a `wsl.exe` that fails or will not start, the
  attempt logs the blocker to `%LOCALAPPDATA%\WslResilience\backup.log`,
  exports and prunes nothing, and exits 3. The next hourly attempt tries again.
- **Once a day:** a successful export writes today's date to `export.last-ok`
  beside the log; later attempts that day exit 0 without exporting.
- **Not seen:** work outside those three probes - a crawl started from a
  terminal, `nohup` or `tmux` - reads as idle, and the export would kill it.
- **After merge, pull first:** the gate runs from the primary checkout, so until
  `/home/natha/OverSteward` has pulled the readiness service every attempt is
  could-not-look. Pull, then re-run `Install-WslResilience.ps1`.
- **Not captured:** Docker Desktop's volumes live in the `docker-desktop`
  distro, which this export does not include.

The full export is the whole-distro rebuild point, not the history. A daily
live backup of `/home/natha`, taken with the distro running (restic), comes in
OS#582, and a health sweep over both backups in OS#583.

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName 'WSL Monthly Backup','WSL Integrity Check' -Confirm:$false
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\WslResilience"
# and, if you set it, revert the Store policy key (value 4 or delete it).
```
