# Sentry-triage cron backstop

ABOUTME: Install + operate the scheduled headless backstop that sweeps the Sentry queue when no session did.
ABOUTME: systemd `--user` timer firing `claude -p` over the unruled-on Sentry issues. NOT enabled by default.

The Sentry triage pass (inbox zero on Sentry *issues*, not zero events — skill
`.claude/skills/sentry-triage/`) has three layers (OverSteward #338, #339). This
is the **backstop**, not the primary:

0. **Sentry's own email alerts.** They tell you something happened.
1. **Session-start sweep (primary).** Each session opens with `/sentry-triage`
   (CLAUDE.md § "Session start — the Sentry triage sweep"), which sweeps every
   unresolved issue with no recorded verdict.
2. **Cron backstop (this unit).** A weekly headless `claude -p` run over
   whatever no session swept — catches quiet stretches, weeks the laptop stays
   closed, and the resident Telegraph operator (which rarely opens a fresh
   session).

Layers 1 and 2 converge on the **same** `/sentry-triage` procedure and the same
`scripts/sentry_triage.py` tool. The cron is **still in-session / Max** —
headless Claude Code uses the subscription, **not** a metered API daemon, and the
tool itself makes zero LLM calls.

## Safe no-op

`sweep` lists every unresolved Sentry issue and subtracts everything already
ruled on in `data/sentry/ledger.jsonl`. When the session-start pass already
drained the queue, the backstop finds nothing, prints `Sentry ledger current —
nothing to triage.`, and exits **0** — so a weekly tick on top of an already-clean
queue costs one short headless session and writes nothing.

**The exit codes carry meaning and the backstop must not collapse them:** `0` is
a measured answer (a queue, or the drained message), `1` means Sentry could not
be read, `2` means it was not configured to look. A failed unit is a finding —
`journalctl` it rather than assuming a quiet week.

## What the unattended run may do

It sweeps, **files** anything real as a repo issue in the owning repo, and
**noise-resolves** what is not a defect. It deliberately does **not** ship code
fixes: a `fixed` verdict flows through a worktree PR like everything else, and
that belongs to an interactive session, not a 04:30 timer.

## Install (systemd `--user`) — explicit, not automatic

Shipping these units does **not** schedule anything. Enabling is a deliberate
operator step (mirroring the dream-cycle backstop) so a timer never surprises
Nathan:

```bash
mkdir -p ~/.config/systemd/user

cp ~/OverSteward/shared/scripts/sentry/sentry-triage.service \
   ~/OverSteward/shared/scripts/sentry/sentry-triage.timer \
   ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now sentry-triage.timer  # <- the explicit enable step
loginctl enable-linger "$USER"                     # keep the timer alive across logout
```

Check it: `systemctl --user list-timers sentry-triage.timer` and
`journalctl --user -u sentry-triage.service -f`.

**Check the unit resolves its executable, too:**

```bash
systemd-analyze --user verify ~/.config/systemd/user/sentry-triage.service
```

A systemd `--user` manager's PATH is the system default
(`/usr/local/bin:/usr/bin:/bin:/snap/bin`) and does **not** carry
`~/.local/bin`, where the Claude Code CLI installs — so the unit names `claude`
by absolute path (`%h/.local/bin/claude`). If `command -v claude` prints
somewhere else on your machine, edit the `ExecStart` line to match. A bare
`claude` verifies as `Command claude is not executable` and the timer would tick
forever without ever launching anything.

Disable: `systemctl --user disable --now sentry-triage.timer`.

## crontab alternative

If you prefer cron to systemd:

```cron
30 4 * * 1  cd $HOME/OverSteward && PYTHONPATH=$HOME/OverSteward/src claude -p "Run the Sentry triage sweep: follow the /sentry-triage skill end to end, but file or noise-resolve only — never ship a code fix unattended. If the ledger is current, no-op." >> $HOME/.claude/sentry-triage-cron.log 2>&1
```

## Running it by hand

```bash
cd ~/OverSteward
PYTHONPATH=$PWD/src claude -p "Run the Sentry triage sweep: follow the /sentry-triage skill."
```

Or drive the deterministic step directly (what the skill calls — no LLM, no
network beyond Sentry's API):

```bash
.venv/bin/python scripts/sentry_triage.py sweep
```

The token comes from `SENTRY_API_TOKEN`, read in-process from the repo-root
`.env` by the tool's own factory. **Never `source .env`, never put the token on a
command line** (credential-hygiene.md) — which is also why the unit sets only
`WorkingDirectory` and `PYTHONPATH` and passes no secret of its own.

## Scope

Backstop trigger only. The sweep, the verdict ledger, and the Sentry client live
in `src/oversteward/sentry/` + `scripts/sentry_triage.py` and are exercised
identically by both triggers. **Out of scope** here: any change to the sweep tool
or the skill, and any cloud-scheduled runner (estate law: scheduled cloud agents
are unreliable — local machinery only).
