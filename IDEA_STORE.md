ABOUTME: Parking lot for ideas that are interesting but not immediately needed.
ABOUTME: Drawn from external projects, conversations, and research. Review periodically.

# Idea Store

Ideas worth remembering but not worth building right now. Review quarterly or when starting a new phase.

---

## From garrytan/gstack (reviewed 2026-03-23; revisited 2026-05-27)

Source: https://github.com/garrytan/gstack — Garry Tan's Claude Code power-user stack.

### PreToolUse Hooks for Governance Enforcement

gstack uses Claude Code's `hooks` frontmatter in skill files to register bash scripts that intercept tool calls. The hook receives JSON on stdin (containing the command or file path) and returns a permission decision (`allow`, `ask`, or `deny`).

**Status (2026-05-27):** Hook infrastructure now exists. PR #47 shipped `~/.claude/hooks/check_db_access.py` — a Bash PreToolUse hook for credential hygiene with block-and-redirect behavior. The harness layer is proven; the managed-block governance hook is now a smaller lift.

**Potential OverSteward use:** A hook that detects edits inside `<!-- [oversteward:managed] -->` blocks and warns the user. This would prevent accidental manual edits to managed sections of CLAUDE.md files.

**Implementation:** Write a `check-managed-block.py` modeled on `check_db_access.py`. Read the target file path from stdin JSON, check whether the edit falls within managed markers, return `{"permissionDecision":"ask","message":"This edit targets an OverSteward-managed block..."}`.

**Why not now:** Sow.py isn't built yet, so managed blocks aren't authoritatively populated. The hook becomes valuable once sow.py is live (Horizon 3). Worth revisiting when H2-1 (cross-repo `.claude/settings.json` parity) forces the issue.

---

### Scope Freeze (/freeze pattern)

A skill that restricts all Edit/Write operations to a declared directory. State persisted to a text file. Useful during debugging to prevent fix-hopping across the codebase.

**Potential use:** During `/investigate`, auto-freeze edits to the affected module.

**Why not now:** Our `/investigate` skill already instructs scope discipline verbally. The hook-based enforcement is an upgrade for when we have the hook infrastructure.

---

### Repo Mode Detection (solo vs collaborative)

gstack auto-classifies repos by analyzing git history — single author = solo mode (more proactive), multiple authors = collaborative mode (more advisory).

**Potential OverSteward use:** Add a `mode` field to registry.yaml entries. Most of Nathan's repos are solo, but GH Obsidian is used on a work machine with different context. Mode could influence Chestertron's proactiveness per-context.

**Why not now:** All current repos are effectively solo. Worth revisiting if Nathan collaborates on any repo.

---

### Skill Chaining via benefits-from Frontmatter

gstack skills declare dependencies: `benefits-from: [prerequisite-skill]`. If the prerequisite hasn't run, the skill offers to run it inline.

**Potential use:** `/review` could declare `benefits-from: [security-audit]` for web projects, offering to run a security pass as part of the review.

**Why not now:** We have four skills total. Chaining adds complexity we don't need yet.

---

### Cross-Model Adversarial Review

For large diffs (200+ lines), gstack's `/review` runs parallel reviews across Claude and OpenAI Codex, then synthesizes findings with confidence weighting for multi-source agreement.

**Status (2026-05-27):** Claude Code's `/ultrareview` skill is a partial realization — multi-agent cloud review of the current branch. Single-vendor though (still Claude). True cross-model adversarial would be the next step.

**Potential use:** For critical deployments (aigranthelper production), run Claude + a second model for adversarial validation.

**Why not now:** Nathan's projects are small enough that `/ultrareview` (single-vendor multi-agent) covers the bar. Revisit when aigranthelper has paying users.

---

### Contributor Mode / Self-Improvement Loop

When enabled, gstack agents file bug reports about gstack itself to `~/.gstack/contributor-logs/`. Max 3 per session. The tool improves itself through usage.

**Potential use:** Chestertron could file improvement suggestions about OverSteward governance during normal work in other repos. Stored in a `feedback/` directory, reviewed during OverSteward sessions.

**Why not now:** Interesting but meta — we should focus on the actual governance system before adding self-improvement loops.

---

### Effort Compression Table in AskUserQuestion

Every decision prompt shows estimated human-team time vs Claude Code time side by side. Reframes decisions toward the more complete option.

**Potential use:** When proposing sync operations or persona deployments, show the effort comparison.

**Why not now:** A bit salesy for our internal-only tooling. The soul doc's "just do it" proactiveness handles this more naturally.

---

### QA Skill with Real Browser (Playwright)

gstack's `/qa` opens a real Chromium browser, clicks through user flows, finds bugs, fixes them with atomic commits, and generates regression tests. Three tiers: quick/standard/exhaustive.

**Potential use:** For aigranthelper and TheAlmoner web projects. Browser-based QA that exercises real user flows.

**Why not now:** Requires Playwright setup and compiled binary infrastructure. Worth building when aigranthelper is in active deployment.

---

### Ship Skill (Automated Release Pipeline)

gstack's `/ship` handles the entire merge→test→review→version-bump→changelog→push→PR→docs pipeline in one command.

**Potential use:** For any repo with CI/CD. Automates the tedious parts of shipping.

**Why not now:** Most of Nathan's repos don't have CI/CD pipelines yet. aigranthelper has GitHub Actions but isn't deploying yet. Revisit post-launch.

---

### Telemetry / Analytics (JSONL Event Log)

gstack logs skill invocations, durations, and outcomes to JSONL files. Enables analysis of which skills are used most, where failures occur, etc.

**Status (2026-05-27):** Partially realized. `data/pipeline_history.jsonl` (H1-2, PR #13) captures daily pipeline snapshots for `/project-status` metrics. Skill-invocation-level telemetry is still future.

**Potential use:** Track OverSteward sync operations, skill usage, and persona deployments over time.

**Why not now:** Over-engineering for current scale. If we get to 20+ repos or multiple users, revisit.

---

### Retro Skill (Weekly Retrospective)

gstack's `/retro` generates weekly retrospectives with shipping streaks, test health trends, and per-person breakdowns. `/retro global` runs across all projects.

**Status (2026-05-27):** Substantially realized by **Fiscus** (added 2026-05-14). Fiscus owns weekly/monthly/quarterly review cadences across the estate, with subject registry, lessons corpus, and an andon channel that aggregates `andon`-labelled issues from every pickup repo. OverSteward emits (`pipeline_history.jsonl`); Fiscus aggregates.

**What's left to ideate:** automated synthesis of the cross-repo activity timeline — shipping streaks, regression-rate trends — that would feed Fiscus's review surfaces. Mostly a Fiscus concern now, not OverSteward.
