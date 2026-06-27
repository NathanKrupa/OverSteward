# Dream-cycle cron backstop

ABOUTME: Install + operate the scheduled headless backstop that runs the dream cycle when no sign-off did.
ABOUTME: systemd `--user` timer firing `claude -p` over the unprocessed-transcript horizon. NOT enabled by default.

The dream cycle (sleep-time memory consolidation, design
`documentation/designs/sleep-time-consolidation.md`) has three triggers
(OverSteward #114). This is the **backstop**, not the primary:

1. **Sign-off (primary).** Nathan signals end-of-day; the operator finishes
   assigned work, then runs the `/dream` skill once.
2. **Stop-hook reminder.** `.claude/hooks/dream_stop_reminder.py` enqueues each
   ending session and reminds you to run `/dream`.
3. **Cron backstop (this unit).** A nightly headless `claude -p` run over any
   transcripts no sign-off drained — catches nights Nathan closes the laptop
   without signing off, crashed/killed sessions, and the resident Telegraph
   operator (which rarely ends cleanly).

All three converge on the **same** `/dream` procedure and the same engine in
`src/oversteward/dream/`. The cron is **still in-session / Max** — headless Claude
Code uses the subscription, **not** a metered API daemon.

## Safe no-op

Step 1 of `/dream` enumerates only transcripts whose content hash is absent from
the processed ledger. When a sign-off already drained the queue, the backstop run
finds nothing and exits clean — so a nightly tick on top of an already-consolidated
day costs one short headless session and writes nothing.

## Install (systemd `--user`) — explicit, not automatic

Shipping these units does **not** schedule anything. Enabling is a deliberate
operator step (mirroring the operator-supervisor pattern) so a timer never
surprises Nathan:

```bash
mkdir -p ~/.config/systemd/user

cp ~/OverSteward/shared/scripts/dream/dream-cycle.service \
   ~/OverSteward/shared/scripts/dream/dream-cycle.timer \
   ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now dream-cycle.timer   # <- the explicit enable step
loginctl enable-linger "$USER"                    # keep the timer alive across logout
```

Check it: `systemctl --user list-timers dream-cycle.timer` and
`journalctl --user -u dream-cycle.service -f`.

Disable: `systemctl --user disable --now dream-cycle.timer`.

## crontab alternative

If you prefer cron to systemd:

```cron
30 3 * * *  cd $HOME/OverSteward && PYTHONPATH=$HOME/OverSteward/src claude -p "Run the dream cycle: follow the /dream skill end to end (memory/docs only, never code). If the ledger is current, no-op." >> $HOME/.claude/dream-cron.log 2>&1
```

## Running it by hand

```bash
cd ~/OverSteward
PYTHONPATH=$PWD/src claude -p "Run the dream cycle: follow the /dream skill."
```

Or drive the deterministic steps directly (what the skill calls):

```bash
PYTHONPATH=$PWD/src python scripts/dream.py cycle unprocessed
```

## Scope

Backstop trigger only. The consolidation engine, the band/merge logic, the privacy
filter, and the doc-only commit live in `src/oversteward/dream/` and are exercised
identically by all three triggers. **Out of scope** here: the reconciliation passes
(design §13), embeddings/graph (§12), and cross-fleet transcript ingestion.
