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
4. **Routine backups.** `Backup-Wsl.ps1` exports weekly to `E:\WSLBackups`
   (separate physical drive from C:), keeping the newest 3. A wipe becomes a
   `wsl --import`.

**Cadence & retention defaults:** weekly backup (Sunday 03:17), keep 3; monthly
deliberate update via `Update-WslSafely.ps1`. Keep the last-good WSL MSI beside
the backups so Path B/C never waits on a download.

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
- **Backup size vs retention:** a ~108 GB ext4 image exports to a large `.tar`.
  **Keep 3** on E: (393 GB free); tune after the first run reports real size.
- **Snapshot consistency:** `wsl --export` briefly **stops the distro** for a clean
  snapshot — schedule it off-hours (the 03:17 default).
- **`run only when logged on`:** the weekly task needs **no stored password** but
  only fires while you're logged in; `StartWhenAvailable` makes it catch up.

## 6. One-paragraph summary

WSL app updates can silently break the Linux platform by removing
`system.vhd`/`modules.vhd`, taking every distro and Docker Desktop down at once.
Because the update cannot be reliably prevented on Windows 11 Home, this process
is defense-in-depth: reduce silent updates where possible, **never** run a bare
`wsl --update` (use `Update-WslSafely.ps1`, which verifies and auto-rolls-back),
catch breakage at logon with an integrity gate, and keep weekly `wsl --export`
backups on a separate drive so any wipe is a few-minute `wsl --import` instead of
a four-hour crisis. Scripts live in `ops/wsl/`; install with
`Install-WslResilience.ps1`.
