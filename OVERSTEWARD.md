ABOUTME: The OverSteward project specification and architecture reference.
ABOUTME: Two-pillar system: governance (sync across contexts) + orchestration (dispatch autonomous agents).

# The OverSteward

**Steward of the House of Krupa's Claude Code estate: keeps every managed context aligned AND dispatches scoped autonomous agents to work the ticket queue across the production repos.**

> "If one thing is done late, everything will be late." The OverSteward ensures that wisdom earned in one quarter of the estate is not squandered by ignorance in another — and that the footmen are dispatched with clear scope, brought home, and never left stranded in a corridor.

---

## Purpose

The OverSteward serves two complementary missions.

### Pillar 1 — Governance (sync)

Keep every managed context's `CLAUDE.md`, souls, personas, and shared skills aligned with the canonical source. Propagate improvements. Prevent drift. Nathan is the only integration layer today, and that does not scale across 14 contexts.

### Pillar 2 — Orchestration (dispatch)

Send scoped autonomous agents to work GitHub issues across the five active production repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus). Provide the async ask-answer loop that closes the human-in-the-loop gap. Keep Nathan informed without making him the queue bottleneck.

Both pillars share a principle: **Nathan is the principal; the OverSteward is the gentleman's gentleman.** Changes are proposed, not imposed. Agents work scoped tickets; Nathan scopes the work. The system has exactly one escape hatch from its own control — Nathan manages the OverSteward directly (`skip_sow: true`).

---

## Problem Statement

**Governance side:**
- Skills and prompt patterns developed in one context don't automatically appear in others.
- `CLAUDE.md` files evolve independently with no shared baseline.
- Souls and personas have no governance layer — they can be silently overwritten or go missing.
- Manual sync across 14 contexts is past the point where it reliably happens.

**Orchestration side:**
- Four production repos generate more ticket work than Nathan can do solo.
- Agents that ask questions mid-run without a capture path are effectively abandoned.
- Without a dashboard, Nathan cannot see the pipeline state at a glance.
- Without a scoping surface, the agent queue starves even when the backlog is deep.

---

## Architecture

### Design Principles (both pillars)

1. **Git is the backbone.** All managed repositories are Git-backed. The OverSteward treats them uniformly.
2. **@file imports, not generated files.** Shared content is composed via `@~/.claude/shared/...` at session start. No build step. The shared source files are canonical; each context's CLAUDE.md holds pointers.
3. **Python for mechanics, Claude Code for intelligence.** File gathering, diffing, Git operations, GitHub scans are Python. Analysis, relevance judgments, scoping decisions, and content proposals are Claude Code.
4. **Ownership markers.** Every managed CLAUDE.md has a `[oversteward:managed]` block (OverSteward owns) and a `[oversteward:local]` block (Nathan owns). Sow operations never touch local.
5. **Inheritance model.** `~/.claude/shared/` is the canonical deployed copy. `oversteward/shared/` is the git-tracked source. Scripts sync source → deployed on every run.
6. **Propose, don't impose.** All sync and dispatch operations surface proposals for approval before meaningful state changes.
7. **OverSteward manages others. Nathan manages OverSteward.** One escape hatch from the system's own control.
8. **Issue queue as the task board** (orchestration). `gh issue list` drives dispatch. Labels drive state. PR merges drive completion. No parallel TODO file for dispatch work.
9. **Deterministic, fail-open mechanics; tokens for judgment only.** Drift detection, hashing, manifest comparison, and diffing are deterministic Python that costs zero Claude tokens and **fails open** — a broken or unreachable check never blocks or mutates an estate it cannot read cleanly; it reports the gap and proceeds. Claude tokens are spent only where genuine judgment is required: conflict resolution, content proposals, scoping. This sharpens principle 3 — "Python for mechanics" also means *cheap, safe, and silent on the happy path*. (Learned from gbrain's zero-LLM auto-link and observe-only guardrail seams; see [documentation/gbrain-learnings.md](documentation/gbrain-learnings.md).)

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      OverSteward Repo                            │
│                                                                  │
│  registry.yaml       ← manifest of all managed contexts          │
│  shared/             ← canonical souls, personas, skills, refs   │
│  contexts/           ← per-context local overrides               │
│  .claude/skills/     ← dispatch, answer, questions,              │
│                        project-status, create-persona            │
│  scripts/            ← project_status.py, tool registry,         │
│                        Phase 2 sync stubs                        │
│  reports/            ← sync check logs                            │
└────────┬────────────────────────────────────────────────────────┘
         │
         ├─── GOVERNANCE ──────────────────────────────────────────
         │   syncs shared → ~/.claude/shared → @file in each repo
         │
         │    ┌─────────┬─────────┬──────────┬─── ... ──────────┐
         │    ▼         ▼         ▼          ▼                  ▼
         │  Home_Ob  billions  ai-assist   macgregor    14 contexts
         │
         └─── ORCHESTRATION ──────────────────────────────────────
             /dispatch launches repo-scoped subagent
             agent works GH issue → PR → auto-merge
             agent blocks → needs-input + structured question comment
             /answer <repo> <n> → posts Nathan's reply → re-dispatch
             /project-status / /questions → pipeline visibility

             Targets: aigranthelper · grantspider · wphelper · ai-assistants
```

---

## Repository Structure

```
oversteward/
├── OVERSTEWARD.md             # This document
├── Stewards_Ledger.md         # Project status and session log
├── MASTER_TODO.md             # Active work queue
├── TODO_BACKLOG.md            # Deferred work
├── SESSION_STATE.md           # Handoff between sessions
├── CLAUDE.md                  # Instructions for Claude Code sessions in this repo
├── registry.yaml              # Manifest of all managed contexts
├── data/
│   └── tool_registry.md       # Regenerated by scripts/tools/generate_tool_registry.py
├── shared/                    # Git-tracked canonical source (deploys to ~/.claude/shared/)
│   ├── souls/
│   │   ├── chestertron.md     # Primary soul
│   │   └── macgregor.md       # MacGregor's soul — never deploys elsewhere
│   ├── personas/
│   │   ├── angelico.md        # Creative Director
│   │   └── herald.md          # Marketing Counselor
│   ├── skills/
│   │   └── create-todoist-task.md
│   ├── references/
│   │   └── wodehouse.md
│   ├── agents/                # Dispatch subagent definitions (source of truth)
│   ├── templates/
│   └── inbox.md               # Update notifications (cleared on first read)
├── contexts/                  # Per-context local overrides
│   └── *.md                   # One file per registered context
├── scripts/
│   ├── project_status.py      # Dashboard backend (Phase 2 — built)
│   ├── orchestration/
│   │   └── setup_dispatch_labels.sh
│   ├── tools/
│   │   └── generate_tool_registry.py
│   ├── workflows/
│   │   └── generate_workflow_registry.py
│   ├── coordinator.py         # Phase 2 — stubbed
│   ├── gather.py              # Phase 2 — stubbed
│   ├── diff.py                # Phase 2 — stubbed
│   ├── sow.py                 # Phase 2 — stubbed
│   └── sweep.py               # Phase 2 — stubbed
├── reports/
│   └── YYYY-MM-DD.md          # Sync check output logs
└── .claude/
    └── skills/
        ├── dispatch/          # /dispatch — launch scoped agents
        ├── answer/            # /answer — post one answer, swap labels
        ├── questions/         # /questions — ad-hoc needs-input view
        ├── project-status/    # /project-status — pipeline dashboard
        ├── refresh-docs/      # /refresh-docs — monthly dated-status-doc sweep
        └── create-persona.md  # Scaffold + deploy a new persona
```

---

## ~/.claude/shared/ Structure

Deployed working copy — not tracked in git. Sync from `oversteward/shared/` on every governance run. All `@file` imports in managed CLAUDE.md files point here.

```
~/.claude/shared/
├── souls/{chestertron,macgregor}.md
├── personas/{angelico,herald}.md
├── skills/
├── references/
├── agents/
└── inbox.md
```

### Connection standard: CLI over MCP

For **GA4, GSC, Railway, Sentry, and Neon**, the CLI is the standard connection
procedure — **not** an MCP server. MCP servers are a live transport that can wedge
a whole session when they churn (the 2026-07-04 disconnect traced to the `sentry`
HTTP MCP; PR #198 emptied that `.mcp.json`). CLIs are stable subprocesses,
appear in the transcript, and pass through the harness credential/read-only
guards that MCP calls bypass. The per-service commands, auth, and read-only
posture live in the canonical reference `shared/references/cli-connection-standard.md`
(deployed to `~/.claude/shared/references/`, sourced into `~/.claude/CLAUDE.md`,
inherited by every repo). A managed context's `.mcp.json` is `{"mcpServers": {}}`
unless a CLI genuinely cannot meet a need. The account-level claude.ai connectors
(Google Drive/Calendar, Canva, Gmail) are operator-disabled in claude.ai settings
— not CLI-touchable.

### Canonical shared scripts (in-repo, not ~/.claude/shared/)

A second class of shared artifact lives at `oversteward/shared/scripts/` — Python tools that need to ship **inside each pickup repo** (so they can `Path(__file__).resolve().parent.parent.parent` to that repo's root), not at user level. Currently:

| Script | Source of truth | Deployed to | Used by |
|---|---|---|---|
| `generate_tool_registry.py` | `oversteward/shared/scripts/tools/generate_tool_registry.py` | `<repo>/scripts/tools/generate_tool_registry.py` | AG, GS, FI, OS |
| `generate_workflow_registry.py` | `oversteward/shared/scripts/workflows/generate_workflow_registry.py` | `<repo>/scripts/workflows/generate_workflow_registry.py` | GS (others as they grow workflows) |
| `guard_main_worktree.py` | `oversteward/shared/scripts/dev/guard_main_worktree.py` | `<repo>/.claude/hooks/guard_main_worktree.py` | all repos (session-per-worktree guard) |
| `guard_shared_venv.py` | `oversteward/shared/scripts/dev/guard_shared_venv.py` | `<repo>/.claude/hooks/guard_shared_venv.py` | all repos (shared-venv mutation guard) |
| `new-session.sh` | `oversteward/shared/scripts/dev/new-session.sh` | `<repo>/scripts/dev/new-session.sh` | all repos (worktree launcher) |
| `worktree_doctor.py` | `oversteward/shared/scripts/dev/worktree_doctor.py` | `<repo>/scripts/dev/worktree_doctor.py` | all repos (pre-removal capture check + repair + teardown) |
| `worktree_db.py` | `oversteward/shared/scripts/dev/worktree_db.py` | `<repo>/scripts/dev/worktree_db.py` | repos with a dockerized test database (GS, AG) |
| `test_worktree_guard.py` | `oversteward/shared/scripts/dev/test_worktree_guard.py` | `<repo>/tests/dev/test_worktree_guard.py` | all repos (guard tests) |
| `format_staged.py` | `oversteward/shared/scripts/dev/format_staged.py` | `<repo>/scripts/dev/format_staged.py` | AG, GS (pre-commit format gate) |
| `require_formatted_commit.py` | `oversteward/shared/scripts/dev/require_formatted_commit.py` | `<repo>/scripts/dev/require_formatted_commit.py` | AG, GS (verify-time format gate) |

Phase-1 sync = byte-copy from source to each pickup repo (any dispatch target). Phase-2 sow.py will fold these into the same workflow as souls/personas. Per-repo configuration (e.g. `data/tool_registry.toml` for project-specific category names) lives in the consuming repo and is **not** managed by OverSteward — only the script itself is canonical.

#### Deploy destinations are derived, not enumerated

Every file in `shared/scripts/dev/` is a family member, and its destination inside a pickup repo follows from its name — no per-member table to keep in step:

| Canonical name shape | Deployed to | Examples |
|---|---|---|
| leading `.` (dotfile config) | `<repo>/<name>` (repo root) | `.gitleaks.toml` |
| a registered hook | `<repo>/.claude/hooks/<name>` | `guard_main_worktree.py`, `guard_neon.py`, `guard_shared_venv.py`, `check_destructive_command.py` |
| `test_*.py` | `<repo>/tests/dev/<name>` | `test_worktree_guard.py`, `test_secret_scan.py` |
| anything else | `<repo>/scripts/dev/<name>` | `new-session.sh`, `with_test_env.py`, `secret_scan.py`, `check_worktree_imports.py` |

`src/oversteward/dev_family.py` encodes exactly this, so a member added to the canonical directory is audited from the next `/sync-status` run with no code change. Before OS#242 each member had to be registered by hand in three places (a gather relpath, a `CANONICAL_DEV_FILES` entry, a diff check), and members that nobody remembered to register — `check_worktree_imports.py`, `guard_neon.py`, `test_secret_scan.py`, `.gitleaks.toml` — were never checked at all.

#### The family is audited against `origin`, never the local checkout

`/sync-status` reads each repo's copies out of `origin/<its registry branch>` (`git fetch` + `git cat-file blob origin/<branch>:<path>`). The resident checkouts run dozens-to-hundreds of commits stale, so hashing their working trees produced **false drift** (local behind origin) *and* **false parity** (an uncommitted local copy that matched canonical while origin did not). Four statuses per member:

| Status | Meaning | Report severity |
|---|---|---|
| `present-identical` | byte-identical to canonical | not reported |
| `drifted` | present but differs from canonical | `drift` |
| `absent-but-doctrine-referenced` | not deployed, **and** the repo's `CLAUDE.md` (read from origin) names the file | `missing` |
| `absent` | not deployed, not referenced — not yet adopted here | `info` |

The doctrine split is the point of the check. A file the repo's own instructions tell agents to run, which does not exist on origin, is a broken instruction — that is how grantspider's `CLAUDE.md` came to point at a `scripts/dev/with_test_env.py` that had never been deployed, and how the `new-session.sh` unshallow guard sat canonically "done" while reaching no repo (OS#242).

#### Byte-identity requires formatter exclusion (decision, OS#241)

The estate rule was "author canonical scripts to the strictest linter across all deploy targets." That rule is unfollowable for a **normalizing formatter**. `ruff format` both wraps lines over the limit and re-joins wrapped lines that fit under it, and the targets disagree: aigranthelper `line-length = 120`, grantspider `99`, OverSteward `100`. Any line between 99 and 120 characters therefore has two incompatible correct forms — line-length is not a strictness ordering, it is two targets pulling opposite ways. Byte-identity across those repos is arithmetically impossible while each repo's formatter owns the file.

**Decision: each repo excludes the canonical family from its own formatter/linter** (`ruff`'s `extend-exclude`, or the equivalent), covering `scripts/dev/`, `.claude/hooks/`, and `tests/dev/` family members. Canonical stays formatted once, in OverSteward, and deploys unchanged. The alternatives were rejected: standardising `line-length` estate-wide churns three repos' history for a cosmetic constant, and per-repo formatting of canonical files abandons byte-identity — which is the entire mechanism by which drift is detectable.

The strictest-linter rule survives for everything a formatter does *not* normalize (rule selection, `DTZ`, import banning, type-checker strictness): canonical must still pass the union of those. Formatting is now excluded from it, not ranked within it.

OverSteward itself has no formatter gate to exclude — ruff is not installed here and its `pyproject.toml` block is vestigial config; the pre-commit gates are gaudi and the secret scan. If ruff is ever installed in OverSteward, it takes the same `extend-exclude`.

#### The formatted bytes must be the committed bytes (OS#78)

Checking formatting locally burns a verify cycle every time a freshly-written file is unformatted (AG#669, GS#1175), so local verify **applies** `ruff format` instead. Applying it alone opens a worse hole, which broke an AG promote on 2026-08-01: commit → verify applies formatting → the marker is written at HEAD → the rewrite sits unstaged → push ships the *committed* (unformatted) bytes → CI's `ruff format --check` fails on a locally-green tree. The marker certified a commit whose bytes nobody verified.

Two canonical family members close it, at the two moments where it can be closed:

| Member | Deployed to | Runs at | Failure means |
|---|---|---|---|
| `format_staged.py` | `<repo>/scripts/dev/format_staged.py` | pre-commit (`local` hook, `pass_filenames: false`) | the formatter rewrote staged Python — re-stage and commit again |
| `require_formatted_commit.py` | `<repo>/scripts/dev/require_formatted_commit.py` | first step of local verify, **before** any marker is written | the tracked tree differs from HEAD after formatting — amend the residue (or commit the work in progress) |

`format_staged.py` is the upstream half: a commit that can never contain unformatted Python leaves no residue for verify to find. `require_formatted_commit.py` is the assertion that survives a bypassed or absent hook — it formats, then requires every tracked path to match HEAD, and reports the two causes separately because the fixes differ (residue → `git commit --amend`; work in progress → commit or stash). It blocks the marker rather than repairing the tree, because a gate that silently amends a commit changes bytes nobody reviewed.

Both delegate to the repo's own `ruff format`, discovered at `<repo>/.venv/bin/ruff`, which reads that repo's `pyproject.toml` — line length, target version, and `extend-exclude` are the repo's, never the script's, so the same bytes deploy to a 99-, 100-, and 120-column repo. `format_staged.py` passes `--force-exclude` so `extend-exclude` still applies to files named explicitly: without it, a hook that passes paths would reformat the very canonical family each repo excludes to stay byte-identical (OS#241 above). Neither script has a formatter of its own to fall back on — an unresolvable `ruff` exits 2 rather than skipping, since a format gate that silently passes is the failure it exists to prevent.

OverSteward carries the canonical source only: with no ruff installed there is nothing to gate, so neither member is deployed into `scripts/dev/` here and neither is registered in `.pre-commit-config.yaml`. The family audit reports both as `absent` (info) for `oversteward` — the correct "not adopted here" reading — and as `absent` for AG/GS until their deploy PRs land. Their tests are OverSteward-local (`tests/dev/test_format_staged.py`, `tests/dev/test_require_formatted_commit.py`) and drive both gates through an injected stand-in formatter, so the canonical behaviour is covered in a repo that has no ruff to run.

### Session-per-worktree discipline

**One git worktree per session — the estate-wide standard.** Parallel Claude/human sessions that share a single checkout collide: a `git checkout`/`switch` in one session yanks another's branch out from under it and strands uncommitted work (it bit GS twice, which is where the guard originated — GS PR #1196). The discipline: each unit of work gets its own worktree under `.claude/worktrees/<name>` on a `session/<name>` branch, cut from the integration branch.

Five byte-identical canonical files (above) make it portable:

- **`guard_main_worktree.py`** — `PreToolUse(Bash)` hook (registered in `<repo>/.claude/settings.json`) that refuses branch checkout/switch in the *primary* worktree. Linked worktrees, file restores (`git checkout -- `, `git restore`), and `git worktree add` are exempt. Override per-command with `CLAUDE_ALLOW_MAIN_GIT=1` (GS also honors `GS_ALLOW_MAIN_GIT=1` for back-compat).
- **`guard_shared_venv.py`** — `PreToolUse(Bash)` hook (same registration) that refuses env-mutating `uv` verbs (`sync`, `venv`, `add`, `remove`, `pip install`, `pip uninstall`, `lock --upgrade`, `run`) when the current tree's `.venv` is a symlink resolving outside it. uv would otherwise stamp the borrowing tree's path into the *shared* venv's console-script shebangs and `__editable__*.pth`, breaking every entry point in every checkout on that venv the moment the borrowing tree is pruned. `run` is on the list because **`uv run` syncs the project environment before it runs anything** — the sync is the rebind, so a bare `uv run pytest` captures the shared venv as surely as `uv sync` does (observed: a repo's venv bound to a `/tmp` dispatch checkout while its primary imported that agent's source, OS#294). An invocation that turns the sync off — `uv run --no-sync`, or `UV_NO_SYNC=1` set on the command or exported, which `new-session.sh` writes into a shared-venv worktree's `.envrc` — is allowed, as are read-only `uv pip list/show/freeze` and any tree with a real `.venv` directory. The refusal names `.venv/bin/<tool>` and both opt-outs, so ordinary work never has to spend the override. Override per-command with `CLAUDE_ALLOW_SHARED_VENV_MUTATION=1`.
- **`new-session.sh`** — self-adapting launcher: base ref is `origin/staging` if it exists (GS/AG), else the remote default branch (trunk-only repos); `PYTHONPATH` is `src/` if present, else the worktree root (Django/flat). One shared `.venv` is symlinked in — `PYTHONPATH` overrides the editable install's `.pth` (verified for pip and uv), so worktrees cost ~nothing. When the venv is shared it also writes `export UV_NO_SYNC=1` into the worktree's `.envrc` and says so in the banner — enforcement without that ergonomic path would just teach every session to reach for the guard's override. (uv repos: invoke `.venv/bin/<tool>` directly, not `uv run`, whose implicit sync re-binds the shared venv.)
- **`worktree_doctor.py`** — the other half of `guard_shared_venv.py`: the guard prevents new capture, the doctor finds capture that already happened and repairs it. `check <worktree>` exits non-zero if anything still points at a worktree — a captured console-script shebang, an `__editable__*.pth`, or a docker compose project whose `working_dir` label names it — and `new-session.sh`'s teardown instruction routes through it, so the estate's own sweep cannot detonate capture. `repair [--repo <path>]` repoints captured shebangs and `.pth` entries at the owning checkout, idempotently. It deliberately will not remove a container or escalate to `sudo` for a root-owned bind-mount skeleton: those are reported with the exact command, and a human decides. `teardown <worktree>` is the one verb that acts rather than reports: it re-runs `check`, refuses on any capture (so a refused teardown changes nothing), names every database the worktree owns, removes the worktree, and only then drops them — most recoverable step first, irreversible last, so a teardown that stops halfway has destroyed nothing (OS#286). It clears only `new-session.sh`'s own `.venv` symlink and `.envrc`, never `--force`, so uncommitted work still refuses the removal. The names are discovered by the suffix `worktree_db.derive` guarantees (`_<slug>`, or `_<digest>` past 63 bytes), which finds all of a repo's stems without the doctor knowing any of them (OS#283). Dropping *is* the teardown, and it is reached only by asking for one.
- **`worktree_db.py`** — names the Postgres database a checkout owns on the shared test container: the primary keeps `<project>_test`, each worktree gets `<project>_test_<slug>`. One container, one database per worktree — not one container per worktree, which would mean N postgres processes, N volumes and runtime port discovery. Every consumer (a `Makefile`'s `TEST_DB_URL`, a local-CI runner, a pre-push alembic gate) must read the name from here; two places deriving it independently is the split brain it exists to prevent. Names that would overflow Postgres's 63-byte identifier limit are hashed on the worktree's absolute path, never truncated — truncation is how two worktrees end up sharing one database.
- **`test_worktree_guard.py`** / **`test_guard_shared_venv.py`** / **`test_worktree_doctor.py`** — pure-logic unit tests for the two guards and the doctor (each locates its subject by walking up to the repo root, so they are depth-independent).

**New-project / new-repo bootstrap** (this IS "the template" — copy these from the canonical source):

```bash
mkdir -p .claude/hooks scripts/dev tests/dev
cp <oversteward>/shared/scripts/dev/guard_main_worktree.py   .claude/hooks/
cp <oversteward>/shared/scripts/dev/guard_shared_venv.py     .claude/hooks/
cp <oversteward>/shared/scripts/dev/new-session.sh           scripts/dev/   # chmod +x
cp <oversteward>/shared/scripts/dev/worktree_doctor.py       scripts/dev/   # chmod +x
cp <oversteward>/shared/scripts/dev/worktree_db.py           scripts/dev/   # chmod +x (repos with a dockerized test DB)
cp <oversteward>/shared/scripts/dev/test_worktree_guard.py   tests/dev/
cp <oversteward>/shared/scripts/dev/test_guard_shared_venv.py tests/dev/
cp <oversteward>/shared/scripts/dev/test_worktree_doctor.py  tests/dev/
cp <oversteward>/shared/scripts/dev/test_worktree_db.py      tests/dev/
# register the hooks in .claude/settings.json under hooks.PreToolUse (matcher "Bash"):
#   python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_main_worktree.py"
#   python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_shared_venv.py"
echo '.claude/worktrees/' >> .gitignore
```

Then document it in the repo's `CONTRIBUTING.md` (or `CLAUDE.md` where there is none).

### Workflow registry & descriptor convention

The **tool registry** catalogs single entry points (CLI scripts, console commands). The **workflow registry** catalogs the higher-altitude thing: multi-step **Python↔Claude workflows** — a Claude Agent SDK Workflow script, a Python pipeline, or an operator-in-loop loop. It is the same durable, regenerable pattern, one level up.

Unlike the tool registry, the workflow registry does **not** sniff the filesystem. Each workflow is described by one hand-authored **descriptor** at `<repo>/.claude/workflows/<name>.md` (co-located with any `.js` Workflow script). `generate_workflow_registry.py` aggregates these descriptors into `<repo>/data/workflow_registry.md`. This decouples the catalog from implementation shape; the accepted trade-off is that descriptors are manual, so the generator validates that any path-shaped `components` entry exists on disk and warns (without failing) when one has drifted.

Descriptor frontmatter schema (YAML) + free-form body:

```yaml
---
name: enrich-drain
summary: One-line what-it-does.            # required
when_to_use: When to reach for this.       # required
kind: workflow-script                      # required: workflow-script | python-pipeline | operator-loop
status: active                             # optional (default active): active | experimental | deprecated
entrypoint: .claude/workflows/enrich-drain.js   # optional: how you start it (path or command)
components:                                # optional: files/commands it touches (paths are drift-checked)
  - scripts/enrich/split_batch.py
  - "grantspider enrich-profile pull-batch"
phases:                                    # optional; omit for workflow-script (the .js meta is authoritative)
  - name: Generate
    detail: N Sonnet agents draft profiles per slice (no write)
  - name: Verify
    detail: Opus grounds + repairs, then apply
    model: opus
---
Free-form body: the file-exchange contract, gotchas, links to docs/PRs.
```

Regenerate after adding or editing a descriptor: `uv run python scripts/workflows/generate_workflow_registry.py`.

### Dual-target deploy: Windows + WSL2

Since 2026-05-20 (AG/GS port off OneDrive), the deploy target is **two homes**, not one:

| Host | Target path |
|---|---|
| Windows | `C:\Users\natha\.claude\shared\` |
| WSL2 (Ubuntu-24.04) | `/home/natha/.claude/shared/` |

A Claude session running natively under WSL resolves `~/.claude/shared/...` against `/home/natha/.claude/`; a Windows session resolves against `C:\Users\natha\.claude\`. They are separate filesystems with no automatic mirror. Every deploy step (sync check, persona scaffold, manual edit) writes to both, or AG/GS (and any future WSL repo) silently break their `@~/.claude/shared/...` imports.

**Inbox caveat:** `shared/inbox.md` is bidirectional state, not deploy-only. The "first context to start a session reads it, applies changes, and clears it" pattern (see below) only sees its own host's copy. To avoid drift: either Nathan appends to both copies, or sync the inbox in both directions before the session-start read. Treat inbox sync as a known soft seam until Phase 2 formalizes it.

---

## Pillar 1 — Governance

### Registry

`registry.yaml` is the manifest of all managed contexts (currently 14). See the file itself for current state. Key fields:

| Field | Purpose |
|---|---|
| `soul` | Primary identity — `chestertron` or `macgregor` |
| `personas_always_on` | Loaded via @file in managed block |
| `personas_available` | Deployed as skill files |
| `skills_always_on` | Shared skills auto-deployed to context |
| `skills_available` | Shared skills available but not auto-deployed |
| `agents_available` | Dispatch subagent types this context can invoke |
| `skip_sow` | If true, governance never writes to this context |
| `dispatch_target` | If true, context is eligible for `/dispatch` |
| `soul_in_local` | If true, soul is defined in local section (billions David/"Sir" variant) |

Full schema reference with precise semantics for every field and for the `soul_in_local` / `skip_sow` / `dispatch_target` contracts: [documentation/registry-schema.md](documentation/registry-schema.md).

### CLAUDE.md Composition

Every managed CLAUDE.md follows this structure. OverSteward owns the managed block entirely. Nathan owns the local block entirely.

```markdown
<!-- [oversteward:managed | synced: YYYY-MM-DD] -->
@~/.claude/shared/souls/chestertron.md
@~/.claude/shared/personas/angelico.md
<!-- [oversteward:managed:end] -->

## Context-Specific Instructions
<!-- [oversteward:local] -->

[Nathan's hand-crafted context instructions — never touched by sow.py]

<!-- [oversteward:local:end] -->
```

### Obsidian Context Differences

| Aspect | VS Code | Obsidian (Claudian) |
|---|---|---|
| Instructions file | `CLAUDE.md` at repo root | `.claude/instructions.md` |
| Skills format | Markdown (`.md`) | JSON (`.json`) |
| Settings | `.claude/settings.json` | `.claude/claudian-settings.json` |

### Sync Workflow (Phase 1 — manual)

1. **Deploy shared.** Copy `oversteward/shared/` → **both** `C:\Users\natha\.claude\shared\` (Windows) **and** `/home/natha/.claude/shared/` (WSL2). See [Dual-target deploy](#dual-target-deploy-windows--wsl2).
2. **Gather.** Read each registered repo's CLAUDE.md and skills inventory.
3. **Diff.** Compute what each context's managed block should contain vs. what it does.
4. **Report.** Write `reports/YYYY-MM-DD.md` listing proposed changes with rationale.
5. **Review.** Nathan approves, modifies, or rejects each proposed change.
6. **Apply.** Write approved changes with safety gates (below).

### Sync Workflow (Phase 2 — planned, not yet built)

Python scripts do the mechanics; Claude handles judgment in bounded slices.

```bash
conda run -n Oversteward python scripts/coordinator.py --report-only
conda run -n Oversteward python scripts/coordinator.py --apply
```

### Sow Safety Gates

- Bail on dirty working tree.
- No stacking — abort if OverSteward already has an open PR on the target.
- Dry-run by default; explicit `--apply` flag to execute.
- Never push to main — always create `oversteward/sync-YYYY-MM-DD` branch.
- Lockfile during execution.

Formal pre-conditions, per-context contracts (including `soul_in_local` write rules), post-conditions, and rejected "convenient" behaviours: [documentation/sow-safety-gates.md](documentation/sow-safety-gates.md). This is the design contract sow must honor before any first real run.

### Deployment manifest & drift classification

The current sow contract compares **canonical-now vs on-disk-now** (two-way). On a hash mismatch for a byte-copy file (skill, persona, hook), the only safe two-way action is to overwrite — but that silently discards a local edit if one exists, and it cannot tell *why* the file diverged. gbrain hit exactly this with `skillpack reference --apply-clean-hunks`: a two-way merge has no record of what was originally deployed, so it clobbers intentional local edits and accidental drift alike.

OverSteward avoids this by recording a **deployment manifest** — the per-file SHA of every byte-copy artifact at the moment sow last deployed it (`reports/manifest.json`, keyed by `context → path → sha`). Drift detection then becomes **three-way** (deployed-baseline vs canonical-now vs on-disk-now) and classifies every managed path into one of four states:

| State | Condition | Meaning | sow/sweep action |
|---|---|---|---|
| `identical` | on-disk == canonical | Up to date | No-op |
| `stale` | on-disk == baseline, baseline != canonical | Canonical moved forward; repo untouched | Safe to redeploy |
| `diverged` | on-disk != baseline **and** on-disk != canonical | Repo's copy was edited locally | **Flag, never silently overwrite.** Surface the diff; Nathan decides — a byte-copy ratchet-treaty violation to correct, or a deliberate downstream hotfix to promote back upstream |
| `missing` | path absent on disk | Never deployed, or deleted downstream | Deploy (sow) / propose (sweep) |

`sync-status` reports use this `identical / stale / diverged / missing` vocabulary directly. Only `diverged` ever requires human judgment; the other three are deterministic, fail-open, and zero-token (principle 9). The byte-copy ratchet treaty assumes *no* intentional local divergence in canonical files — the manifest is what lets OverSteward **detect and surface** a violation of that assumption instead of erasing the evidence. Full mechanics fold into the skill-file deployment contract in [documentation/sow-safety-gates.md](documentation/sow-safety-gates.md).

### Sweep Strategy

OverSteward-deployed persona skills follow naming convention: `persona-{name}.md`. Files not matching this pattern are never touched.

1. For each context, list `persona-*.md` in its skills directory.
2. For each such file, check if the persona is still in `personas_available`.
3. If no longer listed: hash compare against template. Match → propose deletion. Differ → flag, never auto-delete.

### Inbox (governance notifications)

`~/.claude/shared/inbox.md`. OverSteward appends entries when shared resources change. First context to start a session reads the inbox, applies changes, and clears the file.

### Persona Catalogue

| Persona | File | Status | Description |
|---|---|---|---|
| Angelico | `angelico.md` | Active | Creative Director — design, copy, visual strategy |
| Herald | `herald.md` | Active | Marketing Counselor (Praeco Domus) |
| Analyst | `analyst.md` | Planned | Data and financial reasoning specialist |

---

## Pillar 2 — Orchestration

### Dispatch targets

Five production repos, each with a dedicated subagent type defined in `shared/agents/`, all on WSL2:

| Repo | Subagent | Role |
|---|---|---|
| aigranthelper | `aigranthelper-dev` | Django SaaS — Stripe, Neon, paid users |
| grantspider | `grantspider-dev` | US grant data crawler |
| wphelper | `wphelper-dev` | WordPress client toolkit — REST, SEO, FTP, Gutenberg |
| ai-assistants | `ai-assistants-dev` | Almoner package — content, CRM, WP integration |
| fiscus | `fiscus-dev` | Observation-and-kaizen platform — schemas, reviews, lessons corpus |

Each subagent is briefed with the repo's architecture, conventions, self-critique ratchet, and dispatch playbook. Agents run **in-session, foreground** (Agent/Workflow tools) on the Max subscription — never background-async, which is API-metered and subject to silent-termination bug #47936.

### Dispatch loop

```
/dispatch <repo> <issue-number>
    │
    ▼
scoped subagent reads issue → implements → tests → lints
    │
    ├── clean path: opens PR → enables auto-merge → polls → terminal YAML report
    │
    └── blocked path: posts a structured `@nathankrupa question:` comment
                      on the issue (plan / holes / gaudi check / revised plan)
                      labels `needs-input`
                      exits with STOPPED_FOR_INPUT YAML
```

### Async Q&A loop

```
agent blocks → structured question comment on the GH issue
    │
    ▼
Nathan sees it via /questions or the /project-status stale counter
    │
    ▼
Nathan runs /answer <repo> <n>
    ├── shows the pending question
    ├── captures his answer
    ├── posts comment to GH issue
    └── swaps label needs-input → ready-for-agent
    │
    ▼
Nathan re-dispatches the issue (/dispatch <repo> <n>)
```

The previous Chestertron Inbox round-trip (`/morning-digest` → Obsidian file → `/answer-flow`) was retired in H1-5 (PR #16, merged 2026-04-20). GitHub issues are now the only channel for agent Q&A — cross-machine by default, no single-machine Obsidian path.

### Visibility surfaces

| Skill | Cadence | Purpose |
|---|---|---|
| `/project-status` | Ad-hoc | Pipeline dashboard — open issues, open PRs, recent merges, agents in flight, scoping candidates, 30d metrics, stale `needs-input` counter |
| `/questions` | Ad-hoc | Compact list of `needs-input` items, flags stale (>=48h) |
| `/answer` | Ad-hoc (per issue) | Post one answer on a `needs-input` issue and swap labels to `ready-for-agent` |
| `/refresh-docs` | Monthly | Reconcile the dated status docs (Ledger, MASTER_TODO, TODO_BACKLOG, TODO_COMPLETED) against live issue/PR/git state; proposes edits, waits for approval |

### Self-critique gate

Before opening a PR, the dispatched agent runs a coherence audit on its own diff against the dispatch playbook ratchet. Cheap at write-time, reduces review churn and failure modes that have bitten previously (documented in memory files as `feedback_*` entries).

### Scoping surface

When the ready queue drops below threshold, `/project-status` surfaces the oldest unscoped issue per repo so Nathan can scope without having to ask.

---

## Key Decisions — Resolved

### Governance pillar

| Decision | Resolution |
|---|---|
| CLAUDE.md composition method | @file imports pointing to `~/.claude/shared/` |
| Shared content location | `oversteward/shared/` → `~/.claude/shared/` |
| Conflict resolution | Ownership markers — managed regenerated, local untouched |
| Soul separation | `soul:` registry field; chestertron and macgregor never mix |
| Persona deployment | `personas_always_on` (@file) vs `personas_available` (skill files) |
| billions soul exception | `soul_in_local: true` — sow skips soul injection |
| OverSteward self-management | `skip_sow: true` |
| Sweep ownership signal | `persona-{name}.md` naming convention |
| Reports retention | 30-day tracked, archive/ gitignored |
| Headless architecture | Coordinator pattern — Python orchestrates, Claude judges in slices |

### Orchestration pillar

| Decision | Resolution |
|---|---|
| Task board | GitHub issues; labels drive state; no parallel TODO |
| Subagent scope | One subagent type per production repo, briefed with local conventions |
| Blocked-agent protocol | `needs-input` label + structured `@nathankrupa question:` issue comment (plan/holes/gaudi/revised plan) |
| Async Q&A channel | GitHub issue comments — single source of truth, no external inbox file |
| Re-dispatch trigger | `ready-for-agent` label (swapped by `/answer <repo> <n>`) |
| Self-critique gate | Coherence audit against playbook ratchet before PR open |
| Scoping anti-starve | `/project-status` surfaces oldest unscoped issue when queue thins |
| PR merge strategy | Auto-merge on green CI; `--admin` bypass never allowed |

---

## Success Criteria

### Governance

- Nathan can develop a skill in any context and have it appear in all relevant contexts within one sync cycle.
- No `CLAUDE.md` managed block drifts more than one version behind the shared baseline.
- MacGregor's soul has never appeared in any other context's CLAUDE.md.
- Weekly sync check runs without manual intervention (Phase 3).
- Nathan spends zero time manually copying instructions between projects.

### Orchestration

- Dispatch loop cycle time (issue → merged PR, excluding needs-input) holds at or below a known median.
- No `needs-input` issue sits more than 48 hours without Nathan seeing it.
- Ready queue never starves — `/project-status` surfaces scoping candidates before zero-ready state.
- Agent self-critique catches regressions against documented past failure modes before PR open.
- Nathan can see full pipeline state in one command, under 3 seconds.

---

## Phase Roadmap

### Phase 1 — Governance foundation (complete)

All 8 local + remote contexts migrated. Canonical souls and personas deployed. 14 contexts registered. First manual sync check ran 2026-02-26.

### Phase 2 — Tooling (partial)

**Orchestration side (built):**
- [x] `/dispatch` skill and four repo-scoped subagents
- [x] `/questions` (list) and `/answer` (post one reply, swap labels) skills
- [x] `/project-status` skill with Python backend (`scripts/project_status.py`) — 30d metrics + stale `needs-input` counter
- [x] Self-critique gate
- [x] Tool registry generator (`scripts/tools/generate_tool_registry.py`)

**Governance side (not yet built):**
- [ ] `scripts/gather.py` — pull state from all repos
- [ ] `scripts/diff.py` — structured change list (three-way: deployed-baseline vs canonical vs on-disk; classifies `identical / stale / diverged / missing`)
- [ ] `reports/manifest.json` — per-file deployment baseline (`context → path → sha`) written by sow, read by diff/sweep/`sync-status`
- [ ] `scripts/sow.py` — apply changes with safety gates
- [ ] `scripts/sweep.py` — stale persona skill cleanup
- [ ] `scripts/coordinator.py` — orchestrator

### Phase 3 — Automation (partial)

- [x] Orchestration answer loop collapsed to GH-native surfaces (no cron dependency) — H1-5
- [ ] Governance sync on cron (pending Phase 2 scripts)
- [ ] Drift detection notifications

### Phase 4 — Refinement (open)

- [ ] Build Analyst persona (`/create-persona` skill already scaffolded)
- [ ] Deploy Analyst to Stocks and OpportunityMiner
- [x] Pipeline metrics on `/project-status` (PR turnaround, merge rate, needs-input age + stale counter) — H1-2 + H1-5
- [ ] Regression catalog / pre-dispatch lint from past failure memories
- [ ] Full issue-creation → merge cycle time (excluding needs-input stalls) — needs timeline-event fetch

---

## Known Risks

1. **Phase 2 governance scripts stale.** Script stubs have been in place since 2026-02-20 without implementation. Manual sync has been happening irregularly. Either build minimum-viable sow or formally retire the plan.
2. **Partial dispatch metrics.** `/project-status` now reports PR turnaround, merge rate, `needs-input` age + stale counter. Still missing: full issue-creation → merge cycle time excluding `needs-input` stalls (needs timeline-event fetch) and self-critique fire rate (definition undecided).
3. **billions registry modelling.** `soul_in_local: true` works today; Phase 2 sow needs to honor this explicitly or it will overwrite the David variant.
4. **Private-repo branch protection.** GitHub Free tier blocks branch protection on private repos. Discipline-only today; could hide direct-to-main regressions.

---

*Document version: 2026-06-16*
*Status: Governance Phase 1 complete; Orchestration Phase 2 active; Governance Phase 2 pending scope decision. gbrain learnings (deployment manifest, fail-open principle) folded in 2026-06-16.*
