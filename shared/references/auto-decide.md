ABOUTME: The rule a dispatch agent uses to decide WHETHER a decision is worth stopping for — auto-resolve mechanical, surface only taste.
ABOUTME: Adapted from gstack (garrytan/gstack), MIT-licensed — reshaped for OverSteward's needs-input / /answer loop.

# Auto-Decide

When a `<repo>-dev` dispatch agent hits a fork mid-work, its first question is
not "which option?" but "is this even mine to decide?" Most forks a dispatch
agent meets have one defensible answer — a mechanical choice a competent
engineer would make the same way, reversibly, without Nathan in the loop.
Stopping for those wastes Nathan's most expensive resource: his attention.

Auto-decide is the gate that keeps the pipeline moving: **auto-resolve the
mechanical decisions silently, and stop only for the taste decisions — the ones
where reasonable people genuinely disagree.** It is the companion to
`decision-brief.md`: auto-decide answers *whether* to surface a decision;
decision-brief answers *how* to present one once surfaced.

The bias is deliberately conservative. Auto-resolve only clearly-reversible
mechanical choices. **Always** surface anything with prod, security, or
data-shape blast radius, even when a default looks obvious — a reversible-looking
default over an irreversible surface is exactly the trap this gate exists to
catch.

*Adapted from gstack (garrytan/gstack), MIT-licensed. Reshaped into OverSteward's
voice and wired to the dispatch `needs-input` / `/answer` loop.*

## The decision principles

Before raising a question, a dispatch agent settles the fork against these
principles, in order. They are what a mechanical auto-decision *is* — the
defensible default is whatever they point to:

1. **Completeness** — ship the whole thing. Between two options, pick the one
   that covers more edge cases and error paths, not the happy-path shortcut.
2. **Blast radius** — fix what the issue touches (the files it changes plus their
   direct importers). Auto-approve an in-radius expansion only when it is small
   and reversible (a few files, no new infrastructure, no schema or contract
   change). Anything outside the radius is a separate issue, not a silent
   expansion.
3. **Pragmatic** — if two options fix the same thing, take the cleaner one and
   move on. Five seconds choosing, not five minutes.
4. **DRY** — if the change duplicates something that already exists, reuse the
   existing thing instead. A new copy of existing functionality is not a
   defensible default.
5. **Explicit over clever** — a ten-line obvious fix beats a two-hundred-line
   abstraction. Pick what a new contributor reads in thirty seconds.
6. **Bias toward action** — a merged small change beats a stalled perfect one.
   Flag a concern in the PR body; do not block the issue on it.

## Classify the decision

Every fork the agent reaches is one of three kinds. The kind, not the agent's
confidence, decides whether it stops.

**Mechanical — auto-decide silently.** One clearly-right, clearly-reversible
answer that the principles above point to. The agent picks it, notes it in the PR
body, and keeps working. Examples: running the full test suite (always yes),
extracting a helper to stay under the smell threshold (always yes), declining to
widen scope on an already-complete change (always no), picking the idiomatic name
over a clever one.

**Taste — auto-pick a recommendation, but surface it.** Reasonable people could
disagree; more than one path is defensible with different tradeoffs. The agent
still forms a recommendation, but it stops and posts a decision brief rather than
deciding for Nathan. Three natural sources:

1. **Close approaches** — the top two options are both viable, with different
   tradeoffs, and neither dominates on the principles.
2. **Borderline scope** — the change is in the blast radius but larger than
   "small and reversible" (several files, or the radius itself is ambiguous).
3. **Contested defaults** — a review voice, a linter, or a memory law recommends
   differently and has a valid point.

**Blast-radius — ALWAYS surface, never auto-decide.** This is the conservative
override and it wins over everything above. If the fork touches any of these, it
is surfaced regardless of how mechanical it looks:

- **Production** — anything that runs against, migrates, or changes the behavior
  of a live system or a shared production-class database.
- **Security** — auth, secrets, permissions, tokens, credential handling, access
  control, or anything that widens an attack surface.
- **Data shape** — a schema change, a wire/contract change, a type or dict-shape
  refactor that ripples through consumers, or anything a downstream repo reads
  across a seam.

A reversible-looking default over an irreversible surface is still surfaced. When
in doubt about which side of the line a fork sits on, treat it as blast-radius and
surface it — the cost of one extra question is far below the cost of a silent
irreversible mistake. This mirrors the estate's standing laws: no silent
exceptions (`feedback_no_silent_exceptions`), never migrate a shared DB without
explicit auth (`feedback_never_migrate_shared_db`), and split a data-shape
refactor when its consumer ripple is wide (`feedback_consumer_ripple_scope`).

## Per-issue preference: `always-ask` / `auto-ok`

The mechanical/taste line has a per-issue override, carried as a **label** on the
GitHub issue so it travels with the work and survives re-dispatch:

- **`always-ask`** — surface every non-trivial fork on this issue, even ones the
  agent would normally auto-resolve as mechanical. Use it when Nathan wants a
  closer hand on a sensitive or exploratory issue. It **cannot** promote a
  blast-radius decision to auto (blast-radius is always surfaced regardless), and
  it does **not** turn genuinely trivial choices — formatting, an obvious import,
  a rename the code forces — into questions.
- **`auto-ok`** — the agent may auto-resolve borderline *taste* decisions on this
  issue instead of stopping, choosing its recommendation and recording it in the
  PR body. Use it for well-scoped, low-stakes issues where Nathan trusts the
  default. It **never** overrides the blast-radius rule: a prod / security /
  data-shape fork is still surfaced even under `auto-ok`.

Neither label is required; the default (no label) is the mechanical/taste split
above. The blast-radius override is absolute under both labels — it is the one
line no per-issue preference can cross.

## Where it plugs in

- **Dispatch playbook** — the intent-capture protocol runs this gate first. An
  agent classifies the fork *before* it reaches the self-critique gate: a
  mechanical decision never becomes a question; a taste decision that survives
  self-critique becomes a decision brief; a blast-radius decision is always a
  brief. The playbook honors the `always-ask` / `auto-ok` labels when
  classifying.
- **`decision-brief.md`** — once auto-decide says "surface it," the brief is the
  shape the question takes. Auto-decide is the filter; the brief is the envelope.
- **`/answer`** — an auto-resolved mechanical decision leaves a one-line note in
  the PR body ("auto-decided: <fork> → <choice>, mechanical/reversible"), so its
  reasoning is auditable without ever having interrupted Nathan.
