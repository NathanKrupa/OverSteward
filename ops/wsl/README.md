ABOUTME: Overview + usage for the WSL resilience scripts (Windows-side PowerShell, Linux-side restic home backup).
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
| `Backup-Wsl.ps1` | Dated `wsl --export` to `E:\WSLBackups`, keep newest 1 (~131 GB). Asks `scripts/backup_ready.py` first and exports only when the distro is idle; busy or could-not-look logs the blocker to `backup.log` and exits 3. Never runs over a Claude session, a detached GrantSpider run, an estate job or a container. | auto (monthly task) + you |
| `Set-WslUpdatePolicy.ps1` | Reports update-control state; `-Apply` (elevated) disables Store auto-download. Best-effort. | you, once |
| `install-restic.sh`, `home-backup.{service,timer}` | Linux side: install the pinned restic binary, and the systemd `--user` timer for the daily `/home/natha` backup. See below. | you, once |
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
  session, a detached GrantSpider run such as a drain or `supervisor.sh`, a
  running estate job service such as `dream-cycle.service`, or a running docker
  container, each named), or 2 could not look (a probe failed).
- **Only 0 exports.** On 1, 2, or a `wsl.exe` that fails or will not start, the
  attempt logs the blocker to `%LOCALAPPDATA%\WslResilience\backup.log`,
  exports and prunes nothing, and exits 3. The next hourly attempt tries again.
- **Once a day:** a successful export writes today's date to `export.last-ok`
  beside the log; later attempts that day exit 0 without exporting.
- **Not seen:** work outside those four probes - an arbitrary `nohup` or
  `tmux` job - reads as idle, and the export would kill it.
- **After merge, pull first:** the gate runs from the primary checkout, so until
  `/home/natha/OverSteward` has pulled the readiness service every attempt is
  could-not-look. Pull, then re-run `Install-WslResilience.ps1`.
- **Not captured:** Docker Desktop's volumes live in the `docker-desktop`
  distro, which this export does not include.

The full export is the whole-distro rebuild point, not the history. The
history is the daily live backup of `/home/natha` below; a health sweep over
both backups comes in OS#583.

## The daily home backup: restic, with the distro running

Linux-side, not PowerShell. `scripts/backup_home.py` (service
`oversteward.backup.home`) backs up `/home/natha` to the restic repository at
`/mnt/e/WSLBackups/restic` every day at 04:00 through `home-backup.timer`
(`Persistent=true`, so a day the laptop was closed runs at the next boot).

- **Excluded** (regenerable): `~/.claude/tmp`, `~/.cache`, `~/.ollama`, `~/.npm`,
  `~/.vscode-server`, `~/grantspider/data/irs_cache`, and every `.venv` and
  `node_modules` at any depth.
- **Retention:** keeps the last snapshot of each of the last 14 days, 8 weeks and
  6 months, then prunes (`RETENTION` in `oversteward.backup.home`).
- **Self-verifying:** after the backup and prune, one git object (a loose object
  or pack written before the backup started; git never rewrites those) is
  restored from the new snapshot to a temp directory and its sha256 compared
  with the source. Only then is
  `~/.local/state/oversteward/backup/restic.last-ok` (timestamp and snapshot id)
  written.
- **Key:** `C:\Users\natha\AppData\Local\WslResilience\restic.key`
  (`/mnt/c/...` from WSL), passed to restic as `--password-file` and never read
  or printed by the script. It must not live inside the backed-up tree, or the
  snapshot would carry the key beside the repository it unlocks; the script
  refuses a key there.
- **Exit codes:** 0 ok; 1 a step failed (restic error, a source file could not
  be read, the restore did not match) and no marker is written; 2 not
  configured (key, repository, restic or source missing), nothing attempted.
  Read the reason with `journalctl --user -u home-backup`.
- **With the export:** while the backup runs, `backup_ready.py` reports the
  oneshot busy, so the monthly export never kills it.

Set up once, after this merges and the primary checkout has pulled:

```bash
cd /home/natha/OverSteward
ops/wsl/install-restic.sh                       # pinned restic -> ~/.local/bin, sha256-checked

# The key: random, outside /home, copied into the password manager.
K=/mnt/c/Users/natha/AppData/Local/WslResilience/restic.key
mkdir -p "$(dirname "$K")"
( umask 077 && head -c 48 /dev/urandom | base64 -w0 > "$K" )

~/.local/bin/restic init --repo /mnt/e/WSLBackups/restic --password-file "$K"
.venv/bin/python scripts/backup_home.py         # first run by hand; expect exit 0

cp ops/wsl/home-backup.service ops/wsl/home-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now home-backup.timer
```

Restore a path: `restic restore latest --repo /mnt/e/WSLBackups/restic
--password-file <key> --target /tmp/restore --include /home/natha/<path>`.
Without the key the repository cannot be read, so the password-manager copy is
the only way back after a Windows rebuild.

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName 'WSL Monthly Backup','WSL Integrity Check' -Confirm:$false
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\WslResilience"
# and, if you set it, revert the Store policy key (value 4 or delete it).
```
