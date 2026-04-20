ABOUTME: Full schema reference for registry.yaml — every field, its purpose, defaults, and interactions.
ABOUTME: Authoritative contract for scripts/registry.py readers and the future scripts/sow.py writer.

# Registry Schema

`registry.yaml` at the repo root is the single source of truth for every context the OverSteward governs or orchestrates. Every Python reader (`scripts/registry.py`) and every script that writes managed blocks (`scripts/sow.py`, planned) honours this schema.

## Top-Level Structure

```yaml
version: 2
contexts:
  - { ...context entry... }
  - { ...context entry... }
```

- `version` — integer. Bumped when breaking schema changes land. Current: `2`.
- `contexts` — ordered list. Registry order is preserved by `scripts/registry.py`; the dashboard overlays `DISPLAY_ORDER` for historical stability but does not mutate the registry.

## Context Entry Reference

Each context is a YAML mapping. Fields grouped by purpose below.

### Identity

| Field | Type | Required | Purpose |
|---|---|---|---|
| `name` | string | yes | Human-readable label (used in reports) |
| `id` | string | yes | Machine-readable slug. Must be unique. Matches repo folder name and subagent prefix for dispatch targets. |
| `type` | enum `vscode` \| `obsidian` | yes | Drives path conventions (see Paths below) |
| `repo` | string (URL) | yes | Git remote URL. Used by gather/sow for clone + PR operations. |
| `branch` | string | yes | Default branch (`main` or `master`) |

### Paths

| Field | Type | Required | Purpose |
|---|---|---|---|
| `claude_md_path` | string | yes | Relative path to the CLAUDE.md (or `.claude/instructions.md` for Obsidian). Sow writes only inside this file's managed block. |
| `skills_path` | string | yes | Directory for skill files the context consumes |
| `skills_format` | enum `md` \| `json` | no (default `md`) | Skill file format. Obsidian contexts use `json`. |
| `agents_path` | string | no | Directory for subagent definitions. Required on contexts that invoke `/dispatch`. |

### Governance Content

| Field | Type | Required | Purpose |
|---|---|---|---|
| `soul` | enum `chestertron` \| `macgregor` | yes | Primary identity. Sow deploys the soul via `@~/.claude/shared/souls/<soul>.md` import unless `soul_in_local: true`. |
| `personas_always_on` | list<string> | yes | Persona names deployed as `@file` imports inside the managed block. Empty list allowed. |
| `personas_available` | list<string> | yes | Persona names deployed as skill files named `persona-<name>.md`. Empty list allowed. |
| `skills_always_on` | list<string> | yes | Shared skills auto-deployed to the context's `skills_path`. |
| `skills_available` | list<string> | yes | Shared skills available but not auto-deployed. |
| `agents_available` | list<string> | no | Dispatch subagent types this context may invoke. Orchestration metadata only; sow does not deploy agents. |

### Behaviour Flags

| Field | Type | Default | Contract |
|---|---|---|---|
| `skip_sow` | bool | `false` | Total exclusion from governance writes. `scripts/sow.py` MUST refuse to touch this context. Used today for `oversteward` itself. |
| `dispatch_target` | bool | `false` | Context is eligible for `/dispatch`. `scripts/registry.py dispatch-targets` returns contexts where this is `true`. |
| `soul_in_local` | bool | `false` | Soul is defined **inside the local block** (not the managed block). See dedicated section below. |

### Metadata

| Field | Type | Required | Purpose |
|---|---|---|---|
| `tags` | list<string> | no | Free-form tags for filtering and reporting |

---

## `soul_in_local` — Precise Semantics

### What it means

A context with `soul_in_local: true` carries a hand-crafted soul variant inside the `[oversteward:local]` block of its CLAUDE.md. The registry's `soul:` field still names the base soul (e.g. `chestertron`), but the local file may include a modified version — David's "Sir" variant, a project-specific persona layer, etc.

### Current use

Only `billions` (see registry.yaml). The local block contains a David-Chestertron blend that must not be overwritten.

### Contract for sow.py

When `soul_in_local: true` on a context, sow:

- **MUST NOT** emit `@~/.claude/shared/souls/<soul>.md` into the managed block for that context.
- **MUST** still honor `personas_always_on` (those go in the managed block).
- **MUST NOT** read or write anything inside the local block, full stop.
- **MUST** treat a missing local-block soul as a warning (not an error), leaving governance writes otherwise intact.

### Failure mode being prevented

Without this flag, a generic sow run regenerates the managed block and emits the standard `@chestertron.md` import. If the context relies on the local-block variant, the managed import now competes or conflicts with it. At best this produces confusing double-souling; at worst it overwrites the variant if a future refactor widens the managed-block boundaries.

---

## `skip_sow` — Precise Semantics

### What it means

Total governance opt-out. sow never touches this context's CLAUDE.md, skills, or personas.

### Current use

Only `oversteward` (one escape hatch from the system's own control — see OVERSTEWARD.md design principle 7).

### Contract for sow.py

- `skip_sow: true` → sow treats the context as non-existent for write purposes.
- Gather may still read the context for drift reporting.
- Reports MUST mark the context as "skipped by design" so drift is visible but no action is proposed.

---

## `dispatch_target` — Precise Semantics

### What it means

Context is eligible for `/dispatch`. `scripts/registry.py dispatch-targets` returns only these. The dispatch skill, questions skill, morning-digest skill, and project-status dashboard all source their repo list from this filter.

### Current use

`ai-assistants`, `aigranthelper`, `wphelper`, `grantspider`.

### Invariants

- Every `dispatch_target: true` context MUST have a corresponding `<id>-dev` subagent defined in `shared/agents/`.
- `agents_path` SHOULD be set on dispatch targets so subagents ship with the context.

---

## Adding a new context

1. Append an entry under `contexts:` preserving alphabetical order inside each type group (not strict — registry is not sorted).
2. Required fields: `name`, `id`, `type`, `repo`, `branch`, `claude_md_path`, `skills_path`, `soul`, `personas_always_on`, `personas_available`, `skills_always_on`, `skills_available`.
3. If the context defines its own soul variant: set `soul_in_local: true` AND keep the canonical base soul in `soul:` so reports stay coherent.
4. If the context should be dispatchable: set `dispatch_target: true`, add an `agents_available` list, and add a `<id>-dev` subagent file under `shared/agents/`.
5. Run `conda run -n Oversteward python scripts/registry.py dispatch-targets` to verify the new id appears (if dispatchable).

## Adding a new dispatch target

1. Set `dispatch_target: true` on the existing context entry.
2. Add `<id>-dev.md` under `shared/agents/` with the repo's architecture brief.
3. Add the repo to the `DISPLAY_ORDER` constant in `scripts/project_status.py` at the desired column position (optional — defaults to end of table).
4. Verify: `scripts/registry.py info <id>` returns the expected metadata.

## Removing a context

Prefer setting `skip_sow: true` over deletion. Deleting the entry loses history and may orphan deployed skills. `skip_sow: true` keeps the context visible in reports while freezing governance activity.

---

## Schema enforcement

Today `scripts/registry.py` reads fields defensively (`.get()` with None fallback). There is no schema validator. This is acceptable for the single-maintainer phase but should be formalized (e.g. Pydantic model) before multi-contributor growth. Tracked informally in TODO_BACKLOG.

## Related

- `OVERSTEWARD.md` — project overview and pillar structure
- [sow-safety-gates.md](sow-safety-gates.md) — sow.py's operational contract
- `scripts/registry.py` — the canonical Python reader
