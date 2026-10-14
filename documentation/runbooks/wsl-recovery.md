ABOUTME: Runbook + policy for surviving a WSL platform-update wipe (microsoft/WSL #40616 class).
ABOUTME: Failure signature, minutes-not-hours diagnosis, three recovery paths, and the standing resilience policy.

# WSL Resilience — Recovery Runbook & Policy

**Origin:** On 2026-06-17 a WSL **app** auto-update (the 2.7.x line) broke the
Linux environment on this Windows 11 Home machine. It cost ~4 hours and risked
total data loss. Root cause was **not** our code, antivirus, or the distro — it
was [microsoft/WSL #40616](https://github.com/microsoft/WSL/issues/40616) /
[#40488](https://github.com/microsoft/WSL/issues/40488): an interrupted WSL
2.7.3 update silently left `C:\Program Files\WSL\system.vhd` and
`C:\Program Files\WSL\tools\modules.vhd` missing, so every distro failed VM
creation. Data survived only because `ext4.vhdx` is independent of the app
binaries — and **there was no backup.** This runbook + the `ops/wsl/` scripts
exist so this class of failure cannot recur silently and recovery is fast and
data-safe.

---

## 1. Failure signature — recognize it in seconds

You are almost certainly hitting this class if **all** of these are true:

- Launching any distro errors with
  `Wsl/Service/CreateInstance/CreateVm/MountVhd/HCS/ERROR_FILE_NOT_FOUND`
  (the message names a missing `system.vhd`).
- **Docker Desktop also fails to start** at the same time (it runs on WSL2, so
  it dies with the same root cause — a strong tell it's the platform, not one
  distro).
- A WSL app update happened recently (Store update, Windows Update, or a manual
  `wsl --update`), possibly interrupted by a reboot/shutdown.

## 2. Diagnose — one command

From PowerShell:

```powershell
'system.vhd : ' + (Test-Path 'C:\Program Files\WSL\system.vhd')
'modules.vhd: ' + (Test-Path 'C:\Program Files\WSL\tools\modules.vhd')
wsl --version
```

Either path `False` ⇒ confirmed #40616-class. (`ops/wsl/Test-WslIntegrity.ps1`
automates this and exits non-zero when broken.)

## 3. Recover — three paths, fastest first

**Path A — Roll back the WSL app (try first, ~2 min).**
```powershell
wsl --update --rollback
```
Then re-run the diagnosis. Rolling back to the last-good build (e.g. **2.6.3.0**,
the version confirmed healthy in #40616) restores the missing VHDs. If healthy,
**stop here** and do not re-update until the target build is confirmed fixed.

**Path B — Repair the install (if rollback won't run).**
Download the matching WSL release MSI from
<https://github.com/microsoft/WSL/releases>, exit Docker Desktop, right-click
the installer → **Show more options** → **Repair**. Re-run the diagnosis.

**Path C — Reinstall + restore from backup (if A and B fail).**
This is why we keep backups. Your data is in `ext4.vhdx` and your latest export
is on `E:\WSLBackups\`.
```powershell
# 1. Repair/reinstall the WSL app (uninstall the WSL app, reboot, reinstall from the MSI above).
# 2. Confirm the platform is healthy:
wsl --status
# 3. Re-import your data:
wsl --import Ubuntu-24.04 "$env:LOCALAPPDATA\WSL\Ubuntu-24.04" "E:\WSLBackups\Ubuntu-24.04_<latest-date>.tar"
wsl -d Ubuntu-24.04
```
Worst case with a current backup: minutes, not hours, and the only loss is
changes since the last export.

---

## 4. Standing policy (defense-in-depth — prevention can't be trusted)

You **cannot** fully stop WSL from updating itself
([#10799](https://github.com/microsoft/WSL/issues/10799),
[#12675](https://github.com/microsoft/WSL/discussions/12675)), and on Windows 11
Home there is no `gpedit`. So the policy is layered, and the last two layers are
the ones that actually save you:

1. **Reduce silent updates (best-effort).** `Set-WslUpdatePolicy.ps1` documents
   the levers and can disable Store auto-download (`-Apply`, elevated). Also
   pause Windows Update in ~5-week cycles.
2. **Update deliberately, never bare.** Run `Update-WslSafely.ps1` instead of
   `wsl --update` — it verifies integrity and auto-rolls-back on failure. Do it
   in a window where you can afford recovery (not before something time-critical).
3. **Integrity gate.** `Test-WslIntegrity.ps1` runs at every logon (via the
   scheduled task) and alerts immediately if an update broke the platform —
   so you learn at logon, not mid-task.
4. **Routine backups.** `Backup-Wsl.ps1` exports every 28 days to `E:\WSLBackups`
   (separate physical drive from C:), keeping the newest 1. A wipe becomes a
   `wsl --import`. The export does not run over the work it can see: it first asks
   `scripts/backup_ready.py` (run inside the distro, from the primary checkout)
   and exports only on exit 0 (idle). An open but idle Claude session does not
   count: its conversation is on disk and resumes. Busy (1: a working Claude
   Code session - transcript written in the last 30 minutes, or a Bash-tool
   shell running under it - a detached
   GrantSpider run, a running estate job service, or a running docker
   container) or could-not-look (2, or
   a `wsl.exe` that fails) logs the blocker to
   `%LOCALAPPDATA%\WslResilience\backup.log` and exits 3 with nothing exported
   or pruned. Work the probes cannot see - an arbitrary `nohup` or `tmux`
   job - reads as idle and would be killed by the export.

**Cadence & retention defaults:** a full export whenever the last success
(`export.last-ok`) is 28 days old or more. The task runs nightly at 01:17,
retried hourly to ~06:17; a run that is not due exits 0 at once, so a skipped
or failed export is retried every night until one succeeds. A FAILED export,
or a skip more than 35 days after the last success, pops an alert dialog
naming the last success and the latest blocker, at most once a day. Keep 1
(measured ~131 GB on 2026-10-11, of which ~58 GB is regenerable cache; E: is
shared). Monthly deliberate update via `Update-WslSafely.ps1`. Keep the last-good
WSL MSI beside the backups so Path B/C never waits on a download. History does
not come from stacking full exports: the daily restic backup of `/home/natha`
does that, taken with the distro running at 04:00 (`home-backup.timer`) into
`/mnt/e/WSLBackups/restic`, each success stamping
`~/.local/state/oversteward/backup/restic.last-ok` - see
[the daily home backup](../../ops/wsl/README.md#the-daily-home-backup-restic-with-the-distro-running).
A health sweep over the backups is OS#583. Docker Desktop volumes live in the `docker-desktop` distro and
are **not** in this export.

**Test the backup quarterly** — a backup never restored is not a backup:
```powershell
wsl --import wsl-restore-test "$env:TEMP\wsl-restore-test" "E:\WSLBackups\Ubuntu-24.04_<date>.tar"
wsl -d wsl-restore-test -- echo ok
wsl --unregister wsl-restore-test
```

## 5. Tradeoffs (chosen defaults in **bold**)

- **Update cadence:** pinning/delaying updates **delays security fixes**. Mitigated
  by a *monthly* deliberate window rather than freezing forever — the regression
  is fixed in later builds, so staying current (carefully) is the goal.
- **Backup size vs retention:** the ext4 image exports to **~131 GB** (measured
  2026-10-11, uncompressed; ~82 GB in June). E: is shared (not a dedicated backup
  drive), so the default is **Keep 1**. Depth of history is the daily restic
  backup's job ([the daily home backup](../../ops/wsl/README.md#the-daily-home-backup-restic-with-the-distro-running)),
  not the full export's.
- **Snapshot consistency vs work in progress:** `wsl --export` terminates every
  process in the distro to take its snapshot. Rather than pick an hour and hope,
  the export **runs only when the readiness check says the distro is idle** and
  otherwise skips (exit 3) and retries hourly, then nightly. It never kills a
  working Claude Code session, a detached GrantSpider run, a running estate job
  service or a running docker container; work outside those four (an arbitrary
  `nohup` or `tmux` job) is not detected. An idle Claude session left open is
  stopped by the export and resumed afterwards. If every night stays busy, the
  export falls behind, and past 35 days the alert dialog says so and why.
- **`run only when logged on`:** the backup task needs **no stored password** but
  only fires while you're logged in (which is also what lets its alert dialog
  show); `StartWhenAvailable` makes it catch up.

## 6. One-paragraph summary

WSL app updates can silently break the Linux platform by removing
`system.vhd`/`modules.vhd`, taking every distro and Docker Desktop down at once.
Because the update cannot be reliably prevented on Windows 11 Home, this process
is defense-in-depth: reduce silent updates where possible, **never** run a bare
`wsl --update` (use `Update-WslSafely.ps1`, which verifies and auto-rolls-back),
catch breakage at logon with an integrity gate, and keep a 28-day
`wsl --export` on a separate drive, taken only when the distro is idle, so any
wipe is a few-minute `wsl --import` instead of a four-hour crisis. Scripts live in `ops/wsl/`; install with
`Install-WslResilience.ps1`.
