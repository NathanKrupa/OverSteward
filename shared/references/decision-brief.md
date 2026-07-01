ABOUTME: The decision-brief schema a dispatch agent uses when it must stop and ask Nathan a question.
ABOUTME: Adapted from gstack (garrytan/gstack), MIT-licensed — reshaped for OverSteward's needs-input / /answer loop.

# Decision Brief

When a `<repo>-dev` dispatch agent hits genuine ambiguity mid-work and the
intent-capture protocol says the question is worth Nathan's time, the question
it posts is **not** a loose paragraph. It is a decision brief: a fixed, comparable
shape that forces the agent to name the stakes, score coverage, and commit to a
recommendation before it hands the decision back.

This operationalizes three standing estate laws that already demand this in
prose but never encoded the shape:

- **`feedback_architect_decision_completeness`** — a decision must address every
  finding the agent stopped on, not just the headline question.
- **`feedback_service_surface_completeness`** — fix, don't defer; the complete
  option is the goal, not the shortcut.
- **`feedback_no_silent_exceptions`** — no silent auto-decide, no swallowed
  ambiguity; the block is surfaced explicitly and honestly.

*Adapted from gstack (garrytan/gstack), MIT-licensed. Reshaped into OverSteward's
voice and wired to the dispatch `needs-input` / `/answer` loop.*

## When a brief is required

- A dispatch agent reaches the intent-capture protocol (playbook § Intent-Capture)
  and the self-critique gate confirms a real blocker.
- Any agent→Nathan decision where more than one path is defensible and the choice
  is load-bearing (architecture, data shape, destructive scope, missing context).

A brief is **not** required for routine coding, obvious changes, or a question the
agent can answer itself by reading code, the issue body, or the comments.

## The schema

Every brief carries all of these fields, in this order:

```
D<N> — <one-line question title>
Repo/issue/branch: <one short grounding sentence — which repo, which issue #, which branch>
ELI10: <plain English a 16-year-old could follow, 2-4 sentences; name what is being decided and why it matters>
Stakes if we pick wrong: <one sentence — what breaks, what Nathan sees, what is lost>
Recommendation: <choice> because <one-line reason>
Completeness: A=X/10, B=Y/10   (or: Note: options differ in kind, not coverage — no completeness score)
Options:
A) <option label> (recommended)
  ✅ <pro — concrete, observable, ≥40 chars>
  ✅ <second pro — ≥40 chars>
  ❌ <con — honest, ≥40 chars>
B) <option label>
  ✅ <pro — ≥40 chars>
  ✅ <second pro — ≥40 chars>
  ❌ <con — ≥40 chars>
Net: <one-line synthesis of what you are actually trading off>
```

### Field rules

- **`D<N>`** — number your questions within one dispatch: the first is `D1`,
  increment yourself. It is a stable label Nathan can answer by letter ("D1: B").
- **ELI10** — always present, always plain English (not function names). It
  describes the *decision*, not a single option.
- **Stakes if we pick wrong** — one concrete sentence naming what the wrong pick
  costs. This is what makes the question worth Nathan's time.
- **Recommendation** — always present, with a concrete reason. Even a taste call
  gets a recommendation: `Recommendation: <default> — taste call, no strong
  preference`. Exactly one option carries the `(recommended)` marker.
- **Completeness: N/10** — score coverage only when the options differ in coverage.
  **10 = all edge cases handled, 7 = happy path only, 3 = shortcut.** Do not
  fabricate scores. When the options differ in *kind* rather than coverage, drop
  the numbers and write: `Note: options differ in kind, not coverage — no
  completeness score.` Never silently omit both.
- **Per-option ✅/❌** — for every real option: **at least 2 ✅ and at least 1 ❌**,
  each bullet **≥ ~40 characters** (concrete and observable, not filler). The
  honest ❌ is mandatory; an option with no downside is a tell that you have not
  thought it through. Escape hatch for a one-way / destructive confirmation only:
  `✅ No cons — this is a hard-stop choice`.
- **Net** — one line that closes the tradeoff: what you are actually giving up to
  get what you are getting.

### Pre-emit self-check

Before posting the brief, verify every line:

- [ ] `D<N>` header present.
- [ ] ELI10 paragraph present, plus the stakes-if-wrong line.
- [ ] Recommendation line present, with a concrete reason.
- [ ] Completeness scored (coverage) **or** the kind-note present — never neither.
- [ ] Every option has ≥2 ✅ and ≥1 ❌, each ≥~40 chars (or the hard-stop escape).
- [ ] Exactly one `(recommended)` marker (even for a neutral / taste call).
- [ ] Net line closes the decision.
- [ ] The brief addresses **every** finding you stopped on, not just the headline
      (`feedback_architect_decision_completeness`).

## Where it plugs in

- **Dispatch:** the `@nathankrupa question:` comment an agent posts under the
  intent-capture protocol IS a decision brief. The playbook's question template
  is the envelope; this schema is the body.
- **`/answer`:** when Nathan reads the pending question, the brief is what he sees
  — labelled `D<N>`, scored, with a recommendation he can accept by letter. He can
  reply `D1: B`, `B`, or free-form.

## Prose fallback (AskUserQuestion unavailable)

OverSteward dispatch agents post the brief as a **GitHub issue comment** — there
is no live `AskUserQuestion` tool in the dispatch loop, so the prose form below is
the *normal* path here, not an exception. Render it as markdown, not a bullet
grid, but keep the mandatory triad intact:

1. **ELI10 of the decision itself** — plain English, lead with it, name the stakes.
2. **Completeness per option** — an explicit `Completeness: X/10` on each option
   (or the kind-note); never silently drop it.
3. **The recommendation and why** — a `Recommendation: <choice> because <reason>`
   line, and the `(recommended)` marker on that option.

Layout: a `D<N>` title and a one-line "reply with a letter" instruction; the ELI10;
the Recommendation line; then one short paragraph per option carrying its
`(recommended)` marker, its `Completeness: X/10`, and 2-4 sentences of honest
reasoning (its ✅ pros and ❌ con folded into prose — never a bare list). Close with
a `Net:` line. Then STOP and wait — Nathan's typed reply is the decision.

For a one-way / destructive decision (delete, force-push, drop, overwrite), prose
is a weaker gate than a native tool, so make it stronger: state plainly what is
irreversible, require the explicit option letter, and never proceed on a vague
"ok" / "sure" — re-ask instead.
