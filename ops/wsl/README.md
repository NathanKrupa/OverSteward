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
| `Backup-Wsl.ps1` | Dated `wsl --export` to `E:\WSLBackups`, keep newest 1 (~131 GB). Exports only when due (last success 28+ days ago, else exit 0 at once), and asks `scripts/backup_ready.py` first, exporting only when the distro is idle; busy or could-not-look logs the blocker to `backup.log` and exits 3. Never runs over a working Claude session, a detached GrantSpider run, an estate job or a container. A FAILED export, or a skip 35+ days overdue, pops an alert dialog once a day. | auto (nightly task) + you |
| `Set-WslUpdatePolicy.ps1` | Reports update-control state; `-Apply` (elevated) disables Store auto-download. Best-effort. | you, once |
| `install-restic.sh`, `home-backup.{service,timer}` | Linux side: install the pinned restic binary, and the systemd `--user` timer for the daily `/home/natha` backup. See below. | you, once |
| `Install-WslResilience.ps1` | Deploys the scripts to `%LOCALAPPDATA%\WslResilience` and registers the nightly-backup + logon-integrity tasks (and removes the retired `'WSL Weekly Backup'` task). | you, once; again after any script change |

## Quick start (from Windows PowerShell, with WSL running so this path resolves)

```powershell
cd \\wsl.localhost\Ubuntu-24.04\home\natha\OverSteward\ops\wsl   # (after merge to master)

# 1. See current state, no changes:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-WslIntegrity.ps1

# 2. Install the scheduled tasks (nightly backup attempt + logon integrity check):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-WslResilience.ps1

# 3. Run a backup now to validate the path and measure real archive size.
#    It exports only if one is due (exit 0 otherwise) and nothing is running
#    in the distro (exit 3 otherwise -
#    see %LOCALAPPDATA%\WslResilience\backup.log for what blocked it):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Backup-Wsl.ps1

# 4. (optional, elevated) reduce silent Store updates:
#    Start an elevated PowerShell, then:
#    .\Set-WslUpdatePolicy.ps1 -Apply
```

From then on: a full export happens about every 28 days, retried nightly
until one succeeds; the integrity gate alerts at logon if a future update
breaks the platform; and you update monthly via `Update-WslSafely.ps1`.

## The full export: due every 28 days, skip if busy, alert if it falls behind

`wsl --export` terminates every process in the distro to take its snapshot, so
the backup refuses to run over work in progress, and it keeps trying until it
gets a clean night rather than waiting for a particular day:

- **When:** every night at 01:17, retried every hour for 5 hours (to ~06:17).
- **Due:** an attempt goes ahead only when the last success, the date in
  `export.last-ok` beside the log, is 28 days old or more, or there is none.
  Otherwise it exits 0 at once without touching WSL. A successful export
  writes today's date there, so the next 27 nights are no-ops; a skipped or
  failed one leaves it alone, so the next night tries again.
- **Gate:** each due attempt first runs, inside the distro,
  `/home/natha/OverSteward/.venv/bin/python /home/natha/OverSteward/scripts/backup_ready.py`
  (always the primary checkout). It exits 0 ready, 1 busy (a working Claude
  Code session, a detached GrantSpider run such as a drain or `supervisor.sh`,
  a running estate job service such as `dream-cycle.service`, or a running
  docker container, each named), or 2 could not look (a probe failed).
- **Idle Claude sessions do not block.** A session left open counts as working
  only if a transcript in its `~/.claude/projects/<dir>` (subagents included)
  was written in the last 30 minutes, or it has a Bash-tool shell running under
  it. An idle one's conversation is on disk and resumes after the export. All
  sessions opened in the same directory share that directory's transcripts, so
  one working session there keeps its idle siblings busy too. A session whose
  cwd or transcript dir cannot be read makes the gate could-not-look.
- **Only 0 exports.** On 1, 2, or a `wsl.exe` that fails or will not start, the
  attempt logs the blocker to `%LOCALAPPDATA%\WslResilience\backup.log` as
  SKIPPED, exports and prunes nothing, and exits 3. The next hourly attempt,
  or the next night, tries again.
- **A failed export** removes its partial archive, is logged as FAILED, and
  exits 1.
- **Alert:** on a FAILED export, and on a skip when the last success is more
  than 35 days old (or there is none), a Windows dialog names the last success
  date and the latest SKIPPED/FAILED entry from `backup.log`. At most one a
  day (`alert.last-shown` beside the log).
- **Not seen:** work outside those four probes - an arbitrary `nohup` or
  `tmux` job - reads as idle, and the export would kill it.
- **After merge, pull first:** the gate runs from the primary checkout, so until
  `/home/natha/OverSteward` has pulled the readiness service every attempt is
  could-not-look. Pull, then re-run `Install-WslResilience.ps1`.
- **Not captured:** Docker Desktop's volumes live in the `docker-desktop`
  distro, which this export does not include.

The full export is the whole-distro rebuild point, not the history. The
history is the daily live backup of `/home/natha` below; the health sweep at
the end of this page reads both.

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
  with the source. Only then is the marker `restic.last-ok` (timestamp and
  snapshot id) written, twice and byte-identical: first the **mirror** beside
  the key, `C:\Users\natha\AppData\Local\WslResilience\restic.last-ok`, then
  the primary, `~/.local/state/oversteward/backup/restic.last-ok`. Each goes
  through a `.partial` file renamed into place. The mirror sits on C: so a
  Windows-side check can read it while the distro is dead. A mirror that cannot
  be written fails the run (exit 1, `FAILED - marker`) and no primary marker is
  written, so the primary never records a success the mirror lacks.
- **Key:** `C:\Users\natha\AppData\Local\WslResilience\restic.key`
  (`/mnt/c/...` from WSL), passed to restic as `--password-file` and never read
  or printed by the script. It must not live inside the backed-up tree, or the
  snapshot would carry the key beside the repository it unlocks; the script
  refuses a key there.
- **Exit codes:** 0 ok; 1 a step failed (restic error, a source file could not
  be read, the restore did not match, the mirror could not be written) and no
  primary marker is written; 2 not
  configured (key, repository, restic or source missing), nothing attempted.
  Read the reason with `journalctl --user -u home-backup`.
- **With the export:** 04:00 falls inside the export's nightly window. While the
  backup runs, `backup_ready.py` reports the oneshot busy, so the export skips
  that attempt rather than kill it. A 04:00 tick missed while the distro was
  stopped for an export runs when the distro next starts (`Persistent=true`).

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

## The health sweep: are both backups current?

`scripts/backup_health.py` (service `oversteward.backup.health`) is the sixth
session-start sweep in `CLAUDE.md`. It runs inside the distro, writes nothing,
and prints four named rows under a headline that names the count,
`4 backup checks measured — N RED`:

| Row | RED when |
|---|---|
| `snapshot` | the repository's latest snapshot (`restic snapshots --json --latest 1 --no-lock`) is older than 48 h, dated in the future, or absent. Reads **RUNNING**, not RED, while `home-backup.service` is active or activating. |
| `verified restore` | `restic.last-ok` is absent, unparseable, older than 48 h or in the future; it names a snapshot other than the repository's latest; or its C: mirror is absent or differs ("logon canary blind"). |
| `export` | no `Ubuntu-24.04_YYYY-MM-DD.tar` in `E:\WSLBackups` (newest chosen by the date in its name), the newest is zero bytes, or it is older than 45 days. |
| `E: free` | free space on E: is below 1.1 times the newest archive (the next export is written before the old one is pruned), or there is no archive to size it against, or the newest is zero bytes. |

A **NOTE** beneath the export row is not RED: `export.last-ok` absent, or naming
a date other than the newest archive's. `Backup-Wsl.ps1` writes that marker on
each success, but an archive made by an older installed copy of the script has
none: the marker appears with the next export that succeeds after
`Install-WslResilience.ps1` has deployed the current script.

Exit codes: **0** measured, RED rows included; **1** could not read (E: not
mounted, restic or systemctl exited non-zero, unparseable output, or the sweep
crashed); **2** not configured (restic, the key, or the repository with its
parent present, missing).

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName 'WSL Monthly Backup','WSL Integrity Check' -Confirm:$false
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\WslResilience"
# and, if you set it, revert the Store policy key (value 4 or delete it).
```
