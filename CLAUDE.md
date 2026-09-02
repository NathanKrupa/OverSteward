<!-- [oversteward:managed | synced: 2026-03-09] -->
@~/.claude/shared/souls/chestertron.md

At session start, check `~/.claude/shared/inbox.md` for updates. If entries exist, review them and apply any relevant changes, then clear the file.
<!-- [oversteward:managed:end] -->

---

# Working Guidelines

Core rules: `~/.claude/CLAUDE.md`

---

# Project-Specific Configuration

## Python Environment

Bootstrap a fresh checkout with `uv sync --extra dev`. After that, which form
you use depends on which tree you are in:

```bash
# PRIMARY checkout — it owns .venv, so uv's implicit sync is harmless:
uv run python <script>
uv run pytest

# Session WORKTREE — its .venv is a symlink to the primary's:
.venv/bin/python <script>
.venv/bin/pytest
```

**Bare `uv run` is forbidden in a worktree**, including for read-only commands:
it syncs the project environment first, and that sync rebinds the *shared* venv
to the worktree, so the primary checkout starts importing a session branch's
source. `guard_shared_venv.py` refuses it there. Allowed forms:
`.venv/bin/<tool>` (preferred), `uv run --no-sync`, or `UV_NO_SYNC=1 uv run`.
`new-session.sh` writes `UV_NO_SYNC=1` into a worktree's `.envrc` for direnv
sessions.

## Session worktree discipline

**One git worktree per session.** Parallel sessions sharing the primary checkout
collide — a `git checkout` in one strands another's uncommitted work.

```bash
scripts/dev/new-session.sh <name>   # → .claude/worktrees/<name> on session/<name>
```

`.claude/hooks/guard_main_worktree.py` refuses branch checkout/switch in the
primary worktree (file restores, `git worktree add`, and linked worktrees are
exempt). `guard_shared_venv.py` refuses env-mutating `uv` commands from a tree
whose `.venv` is a symlink resolving outside it — uv would stamp the worktree's
path into the shared venv's console-script shebangs and its
`__editable__*.pth`, breaking every entry point in every checkout the moment the
worktree is pruned. Read-only `uv pip list/show/freeze` are untouched.
Deliberate one-offs prefix the command with `CLAUDE_ALLOW_MAIN_GIT=1` or
`CLAUDE_ALLOW_SHARED_VENV_MUTATION=1`.

**Prove imports resolve to the worktree before trusting any gate there** — the
shared venv's editable `.pth` names the primary checkout, so a gate can silently
measure the wrong tree, producing false reds against invisible edits or false
greens on a breaking change it never saw. Export an **absolute**
`PYTHONPATH=<worktree>/src` (a `$PWD`-based export goes stale across `cd`), and
check before the first gate and after any directory change:

```bash
.venv/bin/python -c "import oversteward; print(oversteward.__file__)"
```

**Tear the worktree down through the doctor, never blind** — a shared venv or a
docker compose project can have captured the worktree's path weeks earlier, and
the removal is what detonates it:

```bash
scripts/dev/worktree_doctor.py teardown <worktree>
```

`teardown` re-runs `check`, refuses on any capture (so a refused teardown changes
nothing), names every database the worktree owns, removes the worktree, and only
then drops them — the removal is the step git can still refuse, the drop is the
step nothing can undo. It clears only the `.venv` symlink and `.envrc` that
`new-session.sh` wrote, never `--force`, so a worktree holding real uncommitted
work refuses and keeps its databases. `check` alone exits non-zero and names
every captured console-script shebang, `__editable__*.pth` and compose
container, and reports the worktree's databases as owned state — owned state
never blocks removal. `repair` repoints shebangs and `.pth` entries at this
checkout (idempotent); it reports — never performs — anything needing
`docker rm` or `sudo`.

A worktree's database name comes from `scripts/dev/worktree_db.py` — the primary
checkout keeps `<project>_test`, each worktree gets `<project>_test_<slug>` on
the same container. Read the name from that script; never recompute it. A
worktree can own more than one. When a worktree was removed without the doctor
its database can no longer be named, so recovery reconciles the other way:

```bash
scripts/dev/worktree_doctor.py sweep [--repo <checkout>]   # reports; destroys nothing
scripts/dev/worktree_doctor.py sweep --drop                # destroys what it reported
```

`sweep` matches on *absence* rather than deriving a name, so it is dry-run by
default, names the live worktree each database was matched against, drops
nothing outside this repo's own stems, and never treats the shared
`<project>_test` bench as a candidate. It exits 2 rather than reporting when it
could not look.

This family is canonical here in `shared/scripts/dev/` and deployed to every
repo's `.claude/hooks/` + `scripts/dev/`. See OVERSTEWARD.md §
"Session-per-worktree discipline" for the rollout and new-project bootstrap.

## Running a command with `.env` loaded

**Do not** `source .env` or put a connection-string assignment on a command
line — an unquoted `&` (every Neon URL carries one) leaks the value through bash
job control onto stderr, and stderr is in the transcript. Do not hand-roll a
one-off shim either; use the sanctioned runner, which parses `.env` in-process,
never prints a value, and `exec`s the target command:

```bash
scripts/dev/with_test_env.py make verify
scripts/dev/with_test_env.py -- pytest -k integration
scripts/dev/with_test_env.py --env-file .env.test python -m mytool
```

Existing process environment wins over `.env`. It is stdlib-only and a canonical
byte-copy in the `shared/scripts/dev/` family. Rule:
`shared/references/credential-hygiene.md`.

## Architecture

Principles: `shared/references/architecture-principles.md`.

- **OUTER:** `scripts/`, `.claude/skills/` — parse input, call a service, format output
- **MIDDLE:** services in `src/oversteward/` — business rules, orchestration, decisions
- **INNER:** `registry.yaml`, `contexts/`, `shared/` (canonical source files)

Business logic (diff analysis, conflict resolution, sow decisions) belongs in a
middle-layer service, never in a script.

## Key Files

- **`registry.yaml`** — the manifest of every managed context, and the single source of truth driving sync and dispatch. Additive, surgical edits only; preserve key order and the per-context schema.
- **`architecture.md`** — machine-readable snapshot of repos, cross-repo seams, load-bearing invariants and known liabilities. **Read at scope/plan time** when a task touches more than one repo or any §3 invariant; if a row is wrong, fix it before continuing. Dispatch agents do not read it. Before scoping "edit X and propagate through Y", `git grep` for the managed-block markers and confirm the consumer reads them — if the surface is absent, building it is in-scope, not a follow-up.
- **`OVERSTEWARD.md`** — spec and design decisions. **`Stewards_Ledger.md`** — status and session log. **`MASTER_TODO.md`** (active) + `TODO_BACKLOG.md` + `TODO_COMPLETED.md`.
- **`data/tool_registry.md`** — read it before grepping for a CLI, script or entry point. Regenerate after adding or removing one: `.venv/bin/python scripts/tools/generate_tool_registry.py`. `data/workflow_registry.md` is the same, one altitude up.
- **`SESSION_STATE.md`** — local-only "where we left off" scratchpad; gitignored, **never committed**.

## Session handoff

Durable handoff lives in two already-synced places — auto-loaded memory
(`~/.claude/projects/.../memory/`) and GitHub issues — never in a commit. The
resident Telegraph operator runs in the primary checkout and cannot cleanly
branch per handoff, so committing `SESSION_STATE.md` to `master` used to leave
local-only commits that never pushed *and* a `master` behind origin (OS#90).

- **Never commit `SESSION_STATE.md`**, and **never commit anything directly to the primary checkout's `master`** — all changes flow through a worktree → PR.
- **At session start, while the tree is quiet:** `git pull --ff-only origin master`. Because the primary checkout never carries local commits, this can never diverge. Do **not** pull mid-session; read current code from origin instead (`git show origin/master:<path>`).

## The primary checkout tracks what production runs

**Every primary checkout sits on the branch its production runs**, which is not
always the repo's default — grantspider's default is `staging` while its primary
checkout sits on `main`. Declare it in `registry.yaml` as `primary_branch`
wherever the two differ. `sync_repos.py` reads that key; without it the tool
infers the target from `origin/HEAD`, decides the checkout is on a feature
branch, and **skips the very checkout it should be tending**.

**Never `git pull <remote> <ref>` on a trunk branch.** `git pull` merges into
whatever branch is *checked out*, whatever it is named, so a pull aimed at one
trunk while sitting on another silently rewrites the wrong pointer — a valid
fast-forward, exit 0, no warning. Use the form that names its destination and
cannot rewrite a differently-named branch:

```bash
git fetch origin <branch>
git merge --ff-only origin/<branch>     # or: scripts/dev/sync_repos.py
```

`.claude/hooks/guard_trunk_pull.py` refuses the dangerous shape when a protected
branch is checked out and the pull names a different ref; pulling upstream into
a *feature* branch stays allowed, because a guard that cries wolf gets overridden
reflexively. **The hook is defence in depth, not the control** — it sees only
Claude Code's Bash tool, so a terminal, a Makefile or direnv all bypass it.
`sync_repos.py` on the nightly timer carries the load, and repairs a branch by
itself when the repair is provably lossless (it is ahead of its own remote but
every commit it carries is published on some remote ref). Commits reachable from
**no** remote — genuine unpushed work — stop it and ask for a human. It never
touches a dirty tree, and never a checkout on a branch other than its target.
Enable the sweep once per machine:

```bash
cp shared/scripts/dev/sync-repos.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now sync-repos.timer   # 03:00, ahead of the dream cycle
```

## Session start — the four sweeps

Run these at the start of every session, after the `git pull --ff-only`. **They
are passes, not gates: if Nathan opened the session with a task, his task goes
first** — an urgent production fix never waits behind a doctrine promotion. Each
**requires a recorded verdict**, or the queue never drains: an unrecorded item is
simply at the head of the list again next session.

```bash
/kaizen                                              # one recurring process defect
.venv/bin/python scripts/sentry_triage.py sweep      # what errored
.venv/bin/python scripts/service_liveness.py         # what is down
.venv/bin/python scripts/ag_ops_triage.py sweep      # what AG's users are waiting on
.venv/bin/python scripts/operator_steps.py list      # what Nathan owes
```

**The exit codes carry meaning across all of them and must not be collapsed:
`0` is a measured answer, `1` means the source could not be read, `2` means
nothing was configured to look.** A red exit is a finding to report, not a quiet
morning. A clean result always names the count it checked — "all 20 accounted
for" is a measurement, "ok" is a claim.

- **Kaizen** (`.claude/skills/kaizen/`) drains the estate's own recurring defects one per session; the estate had been re-encountering defects already written down in trajectory notes that nothing read. `kaizen resolve` records the verdict — `deferred` keeps an item queued, only `promoted` and `declined` retire it. `kaizen next` exits **2** when the pattern report is empty over a large corpus: that is a broken instrument, not a quiet backlog. It prints the `clustering` block Fiscus emits and marks a degraded lexical run **UNMEASURED** — rank by reading the cluster's members, never by the number alone.
- **Sentry** (`.claude/skills/sentry-triage/`) drives to inbox zero on *issues*, not events: every issue fixed, filed as a repo issue, or resolved-with-reason, never left unread. `sentry_triage.py record <shortId> fixed|filed|noise-resolved`, with `--resolve` rather than ignore, so a regression reopens loudly.
- **Liveness** reads every `registry.yaml` context carrying a `railway:` block and reports services that are `CRASHED`/`FAILED` or in a state it cannot classify. The Sentry sweep is blind to this — a crashed service emits no Sentry issue, so inbox zero is fully compatible with a core service being dead. A scheduled one-shot that ended `SUCCESS` is completed, not a finding; a one-shot whose last run crashed is down. A project that cannot be read fails the whole sweep rather than silently contributing zero services.
- **AG ops** sweeps untriaged in-app feedback and visitor-reported data corrections over the `/internal/ops/` seam (`.claude/skills/ag-triage/`). Exit 2 today, until `OPS_REPORTS_TOKEN` and `OPS_VERDICTS_TOKEN` are minted.

Adding a Railway project to the liveness sweep is one block in `registry.yaml`:

```yaml
    railway:
      project_id: <project-uuid>
      environment: production
```

## Operator steps go to Todoist, never only the session log

Whenever a session surfaces a step only Nathan can perform — a secret to mint, a
settings paste, a dashboard click, an approval, a TTY-gated command — push it to
his Todoist "Operator Steps" project **in the same breath as telling him**:

```bash
.venv/bin/python scripts/operator_steps.py add "<short imperative>" \
    --description "<the full instructions, self-contained>" [--due <when>]
.venv/bin/python scripts/operator_steps.py done <task-id>   # ONLY after verifying it landed
```

The description must be self-contained — Nathan acts from his phone without the
session log. Mark `done` only on verified completion (the job went green, the
endpoint answers, the setting took), never on his say-so alone.

## Sync Instructions (Phase 1 — Manual)

When Nathan asks for a sync check:

1. Read `registry.yaml` for the current context list.
2. Deploy `shared/` to **both** Claude homes — Windows `C:\Users\natha\.claude\shared\` and WSL2 `/home/natha/.claude/shared/`. Repos on either filesystem resolve `@~/.claude/shared/...` against their own home, so skipping the WSL mirror silently breaks AG/GS. **Exclude `inbox.md` from every sweep** — deploying it overwrites the live inbox in both homes.
3. For each context (skip `skip_sow: true`): check whether the managed block matches what registry specifies.
4. Generate a report in `reports/YYYY-MM-DD.md`.
5. Present proposed changes; wait for approval before running sow.py.
