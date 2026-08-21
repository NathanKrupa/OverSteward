<!-- [oversteward:managed | synced: 2026-03-09] -->
@~/.claude/shared/souls/chestertron.md

At session start, check `~/.claude/shared/inbox.md` for updates. If entries exist, review them and apply any relevant changes, then clear the file.
<!-- [oversteward:managed:end] -->

---

# Working Guidelines

Core rules: `~/.claude/CLAUDE.md`

---

# Project-Specific Configuration

<!-- [oversteward:local] -->

## Python Environment

**Use the project venv** (uv-managed) for running Python commands. Which form
depends on which tree you are in:

```bash
# In the PRIMARY checkout — it owns .venv, so uv's implicit sync is harmless:
uv run python <script>
uv run python -m <module>
uv run pytest

# In a session WORKTREE — its .venv is a symlink to the primary's:
.venv/bin/python <script>
.venv/bin/pytest
```

`uv` auto-creates `.venv/` from `pyproject.toml` on first invocation; subsequent `uv run` calls implicitly activate it. No need to `source .venv/bin/activate` manually.

That implicit sync is exactly why bare `uv run` is wrong in a worktree — it
rebinds the *shared* venv to the worktree, so the primary checkout starts
importing a session branch's source. `guard_shared_venv.py` refuses it there
(see § Session worktree discipline); `uv run --no-sync` and `UV_NO_SYNC=1 uv
run` are allowed, and `new-session.sh` exports `UV_NO_SYNC=1` in the worktree's
`.envrc` so direnv users never notice.

Bootstrap on a fresh checkout:
```bash
uv sync --extra dev
```

## Session worktree discipline

**One git worktree per session.** Parallel Claude/human sessions that share the
primary checkout collide — a `git checkout`/`switch` in one strands another's
uncommitted work. Start every unit of work in its own worktree:

```bash
scripts/dev/new-session.sh <name>   # → .claude/worktrees/<name> on session/<name>
```

The `.claude/hooks/guard_main_worktree.py` `PreToolUse(Bash)` hook **refuses
branch checkout/switch in the primary worktree** (file restores, `git worktree
add`, and linked worktrees are exempt). Deliberate one-offs (a promote, a
rebase) prefix the command with `CLAUDE_ALLOW_MAIN_GIT=1`.

A worktree's `.venv` is a symlink to the primary's, so the two share one
environment. The `.claude/hooks/guard_shared_venv.py` `PreToolUse(Bash)` hook
**refuses env-mutating `uv` commands** (`uv sync`, `uv venv`, `uv add`, `uv
remove`, `uv pip install/uninstall`, `uv lock --upgrade`, and bare `uv run`)
from a tree whose `.venv` is a symlink resolving outside it — uv would stamp the
worktree's path into the shared venv's console-script shebangs and its
`__editable__*.pth`, breaking every entry point in every checkout the moment the
worktree is pruned. Read-only `uv pip list/show/freeze` are untouched, and a
primary checkout (real `.venv` directory) never trips it. Deliberate installs
prefix the command with `CLAUDE_ALLOW_SHARED_VENV_MUTATION=1`.

**`uv run` is on that list because it syncs the project environment before it
runs anything** — that sync is the rebind, even for a read-only command like a
test run. In a worktree, run tools as `.venv/bin/<tool>` (preferred, and never
syncs) or disable the sync explicitly: `uv run --no-sync <cmd>`, or
`UV_NO_SYNC=1 uv run <cmd>`. `new-session.sh` writes `export UV_NO_SYNC=1` into
a shared-venv worktree's `.envrc`, so a direnv session is covered without
thinking about it.

**Prove imports resolve to the worktree before trusting any gate run there.**
The shared venv's editable `.pth` points at the primary checkout, so without
`PYTHONPATH=<worktree>/src` every gate — pytest, gaudi, a schema dump — silently
measures the wrong tree: false reds against invisible edits, or worse, false
greens on a breaking change the gate never saw. `new-session.sh` writes the
export into `.envrc`, but that fires only under direnv — a plain shell (and
every dispatch agent) must export it itself, with an **absolute** path (a
`$PWD`-based export goes stale across `cd`/session resets), and prove
resolution before the first gate and after any directory change:

```bash
.venv/bin/python -c "import oversteward; print(oversteward.__file__)"
```

Recurred 7× across OS/AG/GS (OS#109, OS#330, GS#2079, GS#2100, AG#1131) before
the probe became reflex. AG adds a twist: its cross-repo editable siblings are
MetaPathFinder installs that `PYTHONPATH` cannot shadow — there, reinstall the
siblings into the worktree's own venv instead.

**Tear the worktree down through the doctor, never blind.** A shared venv or a
docker compose project can have captured the worktree's path weeks earlier, and
the removal is what detonates it:

```bash
scripts/dev/worktree_doctor.py teardown <worktree>
```

`teardown` re-runs `check`, refuses on any capture (so a refused teardown
changes nothing), names every database the worktree owns, removes the worktree,
and only then drops them — in that order, because the removal is the step git
can still refuse and the drop is the step nothing can undo. It clears the
`.venv` symlink and `.envrc` that `new-session.sh` wrote (its own scaffolding,
which git counted as untracked), never `--force`, so a worktree holding real
uncommitted work still refuses and keeps its databases. `check` alone exits
non-zero and names every captured console-script shebang, `__editable__*.pth`,
and compose container, and reports the worktree's databases as owned state —
owned state never blocks removal, or every teardown would be blocked forever.
`scripts/dev/worktree_doctor.py repair` repoints the venv's shebangs and `.pth`
entries at this checkout (idempotent); it reports — never performs — anything
needing `docker rm` or `sudo`. `new-session.sh` prints the teardown line for
this reason.

A worktree's database name comes from `scripts/dev/worktree_db.py` — the
primary checkout keeps `<project>_test`, each worktree gets
`<project>_test_<slug>` on the same container. Read the name from that script;
never recompute it. A worktree can own more than one (a repo with a second stem,
as aigranthelper has); the doctor finds them all by the suffix the derivation
guarantees — `_<slug>`, or `_<digest>` once the name has outgrown 63 bytes.

**When a worktree went without the doctor, sweep.** Because every name is
derived from the worktree's *path*, a `git worktree remove` leaves a database
nothing can name again — seven accumulated in grantspider in one evening
(OS#293). The recovery path reconciles the other way:

```bash
scripts/dev/worktree_doctor.py sweep [--repo <checkout>]   # reports; destroys nothing
scripts/dev/worktree_doctor.py sweep --drop                # destroys what it reported
```

It enumerates the databases each running bench container serves, subtracts what
the live worktrees account for, and reports the difference — naming the live
worktree each database was matched against, so the pairing can be audited before
it is authorised. Unlike every other verb this is a match on *absence*, not a
derivation, so it is dry-run by default; it drops nothing outside this repo's
own stems, and the shared `<project>_test` bench is never a candidate. It
refuses (exit 2) rather than reports when it could not look — no `worktree_db.py`
beside it, no answer from docker, no running Postgres — because "I found nothing"
and "I could not look" must never print the same.

This is the estate-wide standard, canonical here in `shared/scripts/dev/` and
deployed to every repo's `.claude/hooks/` + `scripts/dev/`. See OVERSTEWARD.md
§ "Session-per-worktree discipline" for the rollout + new-project bootstrap.

## Running a command with `.env` loaded (sanctioned `with_test_env` runner)

When a command needs secrets from `.env` (the dockerized test backend, `make
verify`, integration `pytest`), **do not** `source .env` or put a `DB-URL=...`
assignment on the command line. The credential-hygiene hook blocks those shapes
because an unquoted `&` in a connection string (every Neon URL carries
`&channel_binding=require`) leaks through bash job control onto stderr — and
stderr is captured in the transcript. Do **not** hand-roll a one-off in-process
shim either; use the sanctioned runner:

```bash
scripts/dev/with_test_env.py make verify
scripts/dev/with_test_env.py -- pytest -k integration
scripts/dev/with_test_env.py --env-file .env.test python -m mytool
```

It parses `.env` in-process (never through the shell), merges the values into the
environment **without ever printing a value**, and `exec`s the target command so
it inherits them. Existing process environment wins over `.env` (matching
`load_dotenv`'s default). Stdlib-only and dependency-free, so it deploys to every
repo. It is a canonical byte-copy in the `shared/scripts/dev/` family (same
deploy + drift-tracking as `new-session.sh` and `guard_main_worktree.py`) — see
`@~/.claude/shared/references/credential-hygiene.md` for the rule it satisfies.

## Architecture

Principles: `@~/.claude/shared/references/architecture-principles.md`

**Layer map for this project:**
- **OUTER:** `scripts/` (coordinator, gather, diff, sow, sweep), `.claude/skills/`
- **MIDDLE:** Orchestration logic within scripts (Phase 2 — currently stubs). As scripts grow beyond stubs, extract services to `src/oversteward/`
- **INNER:** `registry.yaml` (config), `contexts/` (per-repo instructions), `shared/` (canonical source files)

Oversteward is currently a config-management project in Phase 1 (manual sync). When Phase 2 scripts are implemented, business logic (diff analysis, conflict resolution, sow decisions) belongs in a middle-layer service, not in the scripts themselves.

## Key Components

- **registry.yaml** — manifest of all managed contexts (soul, personas, sync behavior)
- **shared/** — canonical soul and persona source files (deploy to `~/.claude/shared/`)
- **contexts/** — per-context local override instructions (one file per managed repo)
- **scripts/** — coordinator, gather, diff, sow, sweep (Phase 2)
- **.claude/skills/create-persona.md** — scaffold and deploy new personas

## Key Files

- **Architecture state:** `architecture.md` — machine-readable snapshot of repos, cross-repo seams, load-bearing invariants, known liabilities, recent moves. **Read at scope/plan time** when a task may touch more than one repo or any §3 invariant. If a row is wrong, fix it before continuing. Dispatch agents do NOT read this — it's a scoping-time tool. **Before scoping "edit X and propagate through Y" work, verify the propagation surface Y actually exists** — `git grep` for the managed-block markers / §2 seam and confirm the consumer reads it; if it's absent, building it is in-scope, not a follow-up (see architecture.md §6).
- **Spec:** `OVERSTEWARD.md` (architecture and all design decisions)
- **Ledger:** `Stewards_Ledger.md` (project status and session log)
- **Todo:** `MASTER_TODO.md` (active) + `TODO_BACKLOG.md` (queued) + `TODO_COMPLETED.md` (archive)
- **Session:** `SESSION_STATE.md` (local-only "where we left off" scratchpad — **gitignored, never committed**; see § Session handoff)

## Session handoff

`SESSION_STATE.md` is a **per-machine local scratchpad** — gitignored, never
committed. The durable, shareable handoff lives in two already-synced places:
**auto-loaded memory** (`~/.claude/projects/.../memory/`) and **GitHub issues**
(the real work tracker). This is deliberate: the resident Telegraph operator runs
in the primary checkout and can't cleanly branch per handoff, so committing
`SESSION_STATE.md` directly to `master` used to leave local-only commits that
never pushed *and* a `master` that fell behind origin — drift that compounded
every session (OS#90).

Drift-prevention rules for the primary checkout:
- **Never commit `SESSION_STATE.md`** (it's gitignored) — write handoff facts to
  memory + issues instead.
- **Never commit anything directly to the primary checkout's `master`** — all
  changes flow through a worktree → PR (see PR workflow in `~/.claude/CLAUDE.md`).
- **At session start, while the tree is quiet:** `git pull --ff-only origin master`
  to pick up merged PRs. Because the primary checkout never carries local
  commits, this fast-forward can never diverge or fail. Do **not** pull
  mid-session (worktree-isolation), and you do **not** need to pull on every
  merge — read current code mid-session from origin (`git show
  origin/master:<path>`) rather than mutating the live tree.

## The primary checkout tracks what production runs

**Every primary checkout sits on the branch its production runs — not the repo's
default branch.** The two differ, and the difference is load-bearing:

| repo | default branch | primary checkout sits on |
| --- | --- | --- |
| grantspider | `staging` | **`main`** — `db migrate-prod run` refuses anywhere else |
| aigranthelper | `main` | `main` |
| OverSteward, wphelper, fiscus, ai-assistants | `main`/`master` | same |

Declare it in `registry.yaml` as `primary_branch` wherever it is not the repo
default. `scripts/dev/sync_repos.py` reads that key; without it the tool infers
the target from `origin/HEAD`, decides the checkout is "on a feature branch",
and **skips the very checkout it should be tending** — which is how aigranthelper
reached 590 commits behind and grantspider's `main` sat on a staging commit
unnoticed.

**Never `git pull <remote> <ref>` on a trunk branch.** `git pull` merges into
whatever branch is *checked out*, whatever it is named, so a pull aimed at a
repo's default branch while sitting on a different trunk branch silently
rewrites the wrong pointer — a valid fast-forward, exit 0, no warning:

```
ec4132a7 main@{2026-08-10 21:56}: pull --ff-only origin staging: Fast-forward
```

Three times in one evening in grantspider (OS#345). Use the form that names its
destination and cannot rewrite a differently-named branch:

```bash
git fetch origin <branch>
git merge --ff-only origin/<branch>     # or: scripts/dev/sync_repos.py
```

`.claude/hooks/guard_trunk_pull.py` refuses the dangerous shape when a protected
branch (`main`/`master`/`staging`) is checked out and the pull names a different
ref. Pulling upstream into a *feature* branch stays allowed — it is an ordinary
idiom, and a guard that cries wolf gets overridden reflexively. **The hook is
defence in depth, not the control**: it sees only Claude Code's Bash tool, so a
terminal, a Makefile or direnv all bypass it. `sync_repos.py` on the nightly
timer is what actually carries the load.

**Repair is automatic when it is provably lossless.** A branch moved onto a
foreign tip is *ahead* of its own remote while carrying nothing unique — every
commit it gained is published on some other remote ref. `sync_repos.py` measures
that (`git rev-list <branch> --not --remotes`) and resets it back by itself.
Only commits reachable from **no** remote — genuine unpushed work — stop it and
ask for a human. It never touches a dirty tree, and never touches a checkout
sitting on a branch other than its target.

Enable the nightly sweep once per machine:

```bash
cp shared/scripts/dev/sync-repos.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now sync-repos.timer   # 03:00, ahead of the dream cycle
```

## Session start — the kaizen pass (OS#332)

**Every session opens by fixing one recurring process defect.** Run `/kaizen`
(skill: `.claude/skills/kaizen/`) as the first act of the session, after the
`git pull --ff-only` above.

The estate had been re-encountering its own defects rather than fixing them —
nine error classes recurring across 9-11 distinct PRs each, every one already
written down in a trajectory note that nothing read (2026-08-08 analysis). This
pass drains that backlog one item per session.

**It is a pass, not a gate.** If Nathan opened the session with an explicit
task, *his task goes first* — surface the item, do his work, then take the item.
An urgent production fix must never wait behind a doctrine promotion. If the
session opens with no assigned work, take the item immediately.

**Record a verdict, or the queue never drains** (`kaizen resolve`). The queue
ranks by measured recurrence, so an unrecorded item is simply the head of the
list again next session. `deferred` keeps an item queued; only `promoted` and
`declined` retire it.

An empty queue is only believable when the detector is working: `kaizen next`
exits **2** when the pattern report is empty over a large corpus. That is a
broken instrument, not a quiet backlog — surface it rather than reporting a
clean morning.

**A confident count is only believable when the detector is measuring.**
`kaizen next` reads the `clustering` block Fiscus emits (mode + degraded) and
prints it above the item: a degraded lexical fallback gets a **DEGRADED** banner
and every count marked `UNMEASURED`, an explicitly-requested lexical run gets
the same mark without the banner, and a report carrying no such block gets a
caveat that it predates mode reporting. Degraded stays **exit 0** — the
fallback still surfaces real lessons — so rank by reading the cluster's members,
never by the number alone (OS#352).

## Session start — the Sentry triage sweep (OS#338)

**Alongside the kaizen pass, sweep the Sentry queue.** Run `/sentry-triage`
(skill: `.claude/skills/sentry-triage/`) as part of opening the session:

```bash
.venv/bin/python scripts/sentry_triage.py sweep
```

Steady state is **inbox zero on Sentry *issues*, not zero events**: every issue
is fixed, filed as a repo issue, or resolved-with-reason, never left unread.
Sentry's own email alerts are Layer 0; this is the pull side, and it is what
makes "nothing new" a fact rather than an assumption. The tool is deterministic
and zero-LLM — it decides what is *unread*, never what the fix should be.

Same shape as kaizen, for the same reasons. **It is a pass, not a gate**, and
**Nathan's assigned work always goes first.** **Record a verdict, or the queue
never drains** (`sentry_triage.py record <shortId> fixed|filed|noise-resolved`)
— an unrecorded issue is at the head of the list again next sweep. Fixed and
noise issues are marked **resolved** in Sentry (`--resolve`), never ignored, so
a regression reopens loudly.

The exit codes carry meaning and must not be collapsed: **0** is a measured
answer (a queue, or `ledger current — nothing to triage`), **1** means Sentry
could not be read, **2** means it was not configured to look. "I found nothing"
and "I could not look" never print the same — a red exit is a finding to report,
not a quiet morning.

## Session start — the liveness sweep (OS#353)

**The Sentry sweep cannot see liveness.** It answers *"what errored"*; a crashed
Railway service emits no Sentry issue at all, so inbox zero is fully compatible
with a core service being dead. GrantSpider's `embedding` sat CRASHED for two
days while the morning sweep reported a clean estate, and was found only because
an unrelated promote happened to rebuild it. Run this alongside the Sentry sweep:

```bash
.venv/bin/python scripts/service_liveness.py
```

It reads every `registry.yaml` context carrying a `railway:` block and reports
the services that are **down** (`CRASHED`/`FAILED`) or in a state it cannot
classify. A scheduled one-shot that ended `SUCCESS` and stopped is *completed*,
not a finding; a deployment mid-flight is *in-flight*, not a finding — but a
one-shot whose last run **crashed** is down, because that run failed.

Same exit-code discipline as the Sentry sweep, for the same reason: **0** is a
measured answer, **1** means Railway could not be read, **2** means nothing was
configured to look at. A project that cannot be read makes the whole sweep fail
rather than silently contributing zero services — a partial sweep reported as
complete is the exact failure this instrument exists to remove. And a clean
result always names the count it checked, because "all 20 accounted for" is a
measurement while "ok" is a claim.

Adding a Railway project to the sweep is one block in `registry.yaml`:

```yaml
    railway:
      project_id: <project-uuid>
      environment: production
```

## Operator steps go to Todoist, never only the session log (Nathan's order, 2026-08-19)

Whenever a session surfaces a step only Nathan can perform — a secret to mint,
a settings paste, a dashboard click, an approval, a TTY-gated command — push it
to his Todoist "Operator Steps" project **in the same breath as telling him**:

```bash
.venv/bin/python scripts/operator_steps.py add "<short imperative>" \
    --description "<the full instructions, self-contained>" [--due <when>]
.venv/bin/python scripts/operator_steps.py list   # session-start: what does Nathan owe?
.venv/bin/python scripts/operator_steps.py done <task-id>   # ONLY after verifying the step landed
```

The description must be self-contained — Nathan acts from his phone without the
session log. Mark `done` only on verified completion (the notify job went green,
the endpoint answers, the setting took), never on his say-so alone. Check
`list` at session start alongside the kaizen/Sentry/liveness sweeps.

## Tool Registry

**When looking for a CLI tool, script, or entry point — read `data/tool_registry.md` first.**

Regenerate after adding/removing tools (`.venv/bin/python`, so it is the same
command in the primary checkout and in a worktree):
```bash
.venv/bin/python scripts/tools/generate_tool_registry.py
```

## Sync Instructions (Phase 1 — Manual)

When Nathan asks for a sync check:
1. Read `registry.yaml` for the current context list
2. Deploy `shared/` to **both** Claude home directories:
   - Windows: `C:\Users\natha\.claude\shared\`
   - WSL2: `/home/natha/.claude/shared/` (via `\\wsl.localhost\Ubuntu-24.04\home\natha\.claude\shared\` or `wsl --exec bash -c "cp ..."`)
   Both must stay in lockstep — repos on either filesystem resolve `@~/.claude/shared/...` against their own home. Skipping the WSL mirror silently breaks AG/GS (and any future WSL repo).
3. For each context (skip `skip_sow: true`): check whether the managed block matches what registry specifies
4. Generate a report in `reports/YYYY-MM-DD.md`
5. Present proposed changes; wait for approval before running sow.py

<!-- [oversteward:local:end] -->
