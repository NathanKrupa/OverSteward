ABOUTME: Conventions for the version-controlled prompt registry that the firmware layer reads from.
ABOUTME: Per-agent subdirectories; semver-style file naming; every row of telemetry pins a version.

# Prompt Registry — Conventions

The "swappable intelligence layer" from [DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §3.3. Prompts and evaluation rubrics live as version-controlled markdown files; code never embeds prompt text inline. The intelligence layer iterates without redeploying the workflow, every prompt change is a reviewable diff with a blame trail, and every telemetry row pins the version that produced it.

This README is the rule sheet. The actual prompts live in per-agent subdirectories.

---

## §1 Layout

```
documentation/prompts/
├── README.md                           # this file
├── matchmaker/
│   ├── explanation@v1.md               # generation prompt
│   ├── quality-rubric@v1.md            # evaluation rubric (LLM-as-judge)
│   └── ...
├── chatbot/                            # Sphere III, when it lands
│   └── ...
└── docs-personalize/                   # Sphere IV, when it lands
    └── ...
```

One subdirectory per agent. One file per `(role, version)` pair. The version suffix is part of the filename so a directory listing is a self-describing changelog.

## §2 Versioning

Files are named `{role}@v{n}.md` where `n` is a monotonic integer. Promotion ([DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §3.5) is always a new file at `v{n+1}`. **Never edit a published version in place** — that breaks the contract that "every telemetry row pins the version that produced it" and silently corrupts the analysis layer.

Permitted edits to a published version:
- Typos that do not change semantics. Annotate the commit message with `prompt-typo: matchmaker/explanation@v3` so the audit trail is clear.
- Removing a comment block at the bottom of the file. Comments are not part of the prompt body, see §3.

Anything that could change a model output is a `v{n+1}`. When in doubt, bump.

## §3 File structure

Every prompt file has the same shape:

```markdown
---
agent: matchmaker
role: explanation                # "generation" or "rubric" prefix is implicit in subdir / filename
version: 1
model: claude-opus-4-7
input_schema: matchmaker.ExplanationInput
output_schema: matchmaker.ExplanationOutput
companion_rubric: matchmaker/quality-rubric@v1   # null if this IS a rubric
created: 2026-05-08
created_by: chestertron+nathan
supersedes: null                  # version this replaces, or null for v1
---

# {Agent}/{Role} — v{n}

## §1 Purpose
One paragraph: what this prompt produces and why.

## §2 Prompt body
The literal prompt. Placeholders use `{snake_case}`. Code substitutes by name, never by position.

## §3 Output contract
Schema reference + worked example.

## §4 Refusal patterns
Inputs the prompt must refuse or abstain on, with the expected output for each.

## §5 Test fixtures
Three to five canonical `(input, expected_output)` pairs. Used by the eval harness on promotion.

## §6 Promotion notes
Only on v2+. What observation in the feedback layer drove this version. Cite the analysis-layer query and the date.
```

Frontmatter is YAML; everything else is markdown. Code reads the frontmatter for routing and validation, and the §2 body as the literal prompt template.

## §4 Substitution rules

Placeholders are named, not positional. The substitution layer (a thin Python helper) validates that every `{name}` in the prompt body is supplied at call time and that no extra keys are passed silently. Missing key → fail loud; extra key → fail loud. **No string interpolation in source files.**

If a placeholder is conditionally optional (e.g. `{org_history}` is empty for first-time users), the prompt body uses an explicit conditional block:

```
{?org_history}
Past grants this org has received: {org_history}
{/org_history}
```

The substitution layer treats `{?name}...{/name}` as "render this block only when `name` is non-empty." Keeps the prompt readable and removes the temptation to write `{org_history_or_empty}` boilerplate at call sites.

## §5 Output contract

Every prompt declares an `output_schema` in frontmatter. The schema name is a Pydantic model id that the code resolves at call time. The model validates the LLM's output before any telemetry row is written.

**Validation failure is a structured failure**, not a silent retry. Telemetry records `outcome: "error"` + `error_code: "MALFORMED_OUTPUT"` per the matchmaker schema. Retry policy is *separate* from validation — if a retry happens, it produces a *second* telemetry row with the same `run_id`, the same `step`, and a new `step_index`.

## §6 Rubric files

Rubrics are prompts too. Same structure, same versioning. The difference is that the rubric's input includes the *other* prompt's output, and the rubric's output is a structured score against named dimensions.

A rubric file's `companion_rubric` frontmatter is null. A generation file's `companion_rubric` points to the rubric that evaluates it. If a generation prompt has no companion rubric, its `confidence_distribution` field in telemetry stays empty — that is a deliberate choice, not a bug, and should be called out in the file's §1.

## §7 Promotion workflow

1. Observation lands in the weekly analysis-layer review ([DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §3.4).
2. Draft `{role}@v{n+1}.md`. Fill the §6 promotion notes section citing the observation, the query that surfaced it, and the date.
3. Run the eval harness against the v{n} fixtures plus any new fixtures the observation suggests. Both versions must pass the v{n} fixtures (regression guard) and the new version must pass the new fixtures.
4. Open a PR. Reviewable diff is `{role}@v{n}.md` (red) vs `{role}@v{n+1}.md` (green); both are in the tree until v{n} is retired.
5. On merge: bump the active version pointer (config file, env var, or feature flag — see §8) and add a row to `data/promotions.jsonl` with `{ts, agent, role, from_version, to_version, observation_query, observation_date}`.
6. v{n} stays in the tree until at least 30 days have elapsed and no telemetry row references it; then it can be deleted in a separate PR. The 30-day window is so any in-flight analysis-layer notebooks can still resolve historical rows.

## §8 Active-version pointer

The "active" version of each prompt is set by config, not by which files exist. Three valid pointer mechanisms, in order of preference:

1. **Config file** — `config/prompts.yaml` in the implementing repo. Pinned per environment (`dev`, `staging`, `prod`). Default for all production prompts.
2. **Environment variable** — `MATCHMAKER_EXPLANATION_PROMPT=v3`. For ad-hoc experiments without a config-file commit.
3. **Feature flag** — when running an A/B test, the flag returns a different version per user/cohort. The `prompt_version` field in telemetry records the version the *individual run* used.

Never read the active version from "newest file in directory" — that creates the silent-edit failure mode §2 forbids.

## §9 Implementation home

The v0 design lives here in oversteward (where the blueprint lives). On implementation, prompts move to the consuming repo:

- **Matchmaker prompts** → `aigranthelper/apps/matchmaker/prompts/` (Sphere I lead).
- **Chatbot prompts** → `aigranthelper/apps/chatbot/prompts/` (Sphere III, deferred).
- **Docs personalization prompts** → `aigranthelper/apps/docs/prompts/` (Sphere IV, deferred).

When the move happens, the oversteward copy becomes a redirect: `documentation/prompts/matchmaker/README.md` points to the implementing repo path and the v0 history files are retired (the implementing repo's git history is now the audit trail).

## §10 Maintenance

- Bump version on any semantic change. Document the why in §6 of the new file.
- Annotate typo-only edits in the commit message.
- Promotion log lives at `data/promotions.jsonl`.
- Retire v{n} files no sooner than 30 days after demotion.
- If a sphere ships a prompt and never produces a promotion row in 90 days, either the analysis layer is dark or the prompt is genuinely stable — call out in the next ROADMAP review.

*Last updated: 2026-05-08 (v0 — companion to DETERMINISTIC_AGENTS.md §3.3 and matchmaker-instrumentation.md §8).*
