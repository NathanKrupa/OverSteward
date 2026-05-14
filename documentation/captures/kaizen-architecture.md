ABOUTME: Honest critique of the weekly-review notebook sketch against best practices; redesign as a foundational kaizen architecture spanning every system the House of Krupa runs.
ABOUTME: Multi-subject registry, PDCA cycle with standardize step, andon cord, lessons corpus, cross-sphere correlation.

# Observation + Kaizen — Architecture

**Companion to:** [weekly-review-notebook.md](weekly-review-notebook.md), [DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md), [matchmaker-instrumentation.md](matchmaker-instrumentation.md).
**Status:** v0 — critique + redesign proposal. Supersedes the matchmaker-only scope in `weekly-review-notebook.md` §4.
**Purpose:** answer Nathan's three-part question — how does the sketch compare to best practices, what is foundationally missing, what is the right multi-subject shape — with diplomatic honesty rather than additive optimism.

---

## §1 What "best practice" looks like in 2026

The reference points the sketch should be measured against. Not all apply to a one-person shop today, but all of them shape the *architecture* the shop will grow into.

### 1.1 The observation pillars
- **Metrics, logs, traces.** Three distinct concerns. The sketch has logs (JSONL) but no proper traces (a `run_id` that is uuid-v7 is not the same as a `trace_id` with parent/child span structure and baggage propagation across boundaries — the Kit webhook, the export endpoint, and the self-report endpoint are three system boundaries the sketch crosses without an OpenTelemetry-style trace).
- **Sample-rate continuous evaluation in production.** Rubric runs on every Nth output, streaming to a dashboard, not only in batch on Monday morning. The sketch is batch-only.
- **Drift detection.** Distribution shift in inputs (profile-completion patterns), outputs (model confidence), and behaviour (dismissal patterns). The sketch tracks data freshness for the producer corpus but no model-output drift or user-behaviour drift.

### 1.2 Eval-driven development
- **Offline eval gate on every prompt change.** CI runs the rubric over a curated test set; a regression on the existing fixtures blocks the merge. The sketch mentions fixtures but does not wire them to CI.
- **Statistical significance, not eyeball.** A drop from 0.36% to 0.96% fabrication rate looks like a 3× spike — but with N=312 evaluations, the confidence interval is wide. The sketch's recommendations don't reason about uncertainty.
- **Labeled-set growth pattern.** Each promotion expands the canonical fixture set with the case that drove it. The sketch does not specify this — fixtures are an artifact, not a growing dataset.

### 1.3 Closed-loop ML / feedback into model
- **Gold signal flows into training data**, not just into Nathan's review. Real shops route confirmed-good examples into a retrieval-augmentation index (so the matchmaker can learn from "matches like this one led to applications") or a fine-tune set. The sketch reports on the gold signal; it does not route it.

### 1.4 Experimentation infrastructure
- **A/B framework as a first-class system.** Experiment registry, assignment service, variance reduction (CUPED), sequential testing to stop early on clear winners. The sketch mentions `render_variant` once in §5.7 and does no more.
- **Causality vs correlation.** Every descriptive query in the sketch confuses correlation with causation. "Users who skip `year_founded` apply 40% less" is a correlation; the causal claim ("requiring `year_founded` would lift applies") needs an experiment.

### 1.5 Kaizen primitives (Lean / Toyota Production System)
- **PDCA cycle** — Plan, Do, Check, **Act-with-Standardize**. The sketch covers Plan (promotion candidate), Do (deploy v{n+1}), Check (next week's review). It is silent on Standardize: turning each improvement into a regression guard, a test fixture, a lint rule, a documented invariant. **Without Standardize, the same problem returns six months later.**
- **Andon cord** — anyone can stop the line when they see a problem. The sketch is top-down (Nathan reviews, Nathan promotes). A foundational kaizen system has structured paths for distributed observation — users, agents, future analyst persona, even Nathan in the middle of a different session.
- **Genchi genbutsu** ("go and see") — the analyst periodically inspects raw user sessions, not just aggregates. The sketch lives entirely in aggregate-land.
- **Jidoka** (autonomation) — automatic detection of abnormality, automatic stop. The sketch has anomaly alerts but no auto-stop behaviour (e.g. auto-revert a prompt promotion if its first-24-hour rubric scores breach a threshold).
- **Heijunka** (leveling) — don't dump 20 promotion candidates in one week. The sketch's §6 table can grow unbounded; there is no pacing discipline.
- **5 whys / fishbone** — structured root-cause analysis. The sketch's §3 fabrication-watch narrative is at level 1 ("v2 prompt is the cause"); 5-whys would push to level 5 ("we promoted v2 in a hurry because the deploy window was closing because we conflated test-with-production data because…").

### 1.6 Decision and knowledge infrastructure
- **Architecture Decision Records (ADRs)** — context, decision, alternatives considered, consequences, follow-up review date, status. The sketch's `decisions.jsonl` is too thin: a row per decision is fine for *counting* decisions, not for *understanding* them.
- **Postmortem template + incident library.** Every anomaly gets a structured postmortem; the corpus is searchable when something similar recurs. The dispatch lineage already has this pattern in the agent memory files (`feedback_*.md`); the sketch does not extend it.
- **Lessons-learned corpus** as durable, searchable knowledge. Distinct from decisions (which record *what we chose*) and postmortems (which record *what went wrong*). The lessons corpus records *what we learned* — phrased as principle, not as incident.
- **"Standardize the gain"** — every improvement is encoded into something a future contributor will encounter: a fixture, a lint rule, an invariant in `architecture.md`, a checklist item in the playbook. The OverSteward `architecture.md` §3 invariants table is a strong instance of this; the sketch does not connect to it.

### 1.7 Qualitative input as first-class telemetry
- **Customer interviews, support tickets, NPS, retrospectives.** The richest signal often comes from qualitative sources. The sketch is purely behavioural-metrics-driven.
- **User-submitted output feedback.** "This match was wrong because X" structured feedback channel, routed into the same telemetry pipeline. Not in the sketch.

### 1.8 Unit economics
- **Cost per outcome.** $ per match presented, $ per gold signal earned, $ per user retained. The sketch tracks token cost per row but does not aggregate to economic units.
- **ROI on improvements.** When a promotion lands, what was the net change in cost-per-outcome? Without this, the firmware compounds in quality but might silently regress in economics.

### 1.9 Meta-loop — improving the improvement system
- **Lead time from observation → promotion → measurable impact.** How long, on average, does it take? Trending up or down?
- **Promotion success rate.** What fraction of promotions actually produced their hypothesized improvement?
- **Quarterly retrospective on the kaizen system itself.** Is the loop working? Where is friction? Where are we observing-without-improving?

---

## §2 Honest critique of the sketch

Item-by-item, where the weekly-review-notebook sketch lives on the spectrum from "missing" to "best practice."

| Best practice | Sketch status | Severity |
|---|---|---|
| Three observation pillars (metrics, logs, traces) | Logs only; no proper traces | **Material gap** |
| Sample-rate continuous eval in production | Batch-only | **Material gap** |
| Drift detection (input/output/behaviour) | Producer-data freshness only | Notable gap |
| Offline eval gate on every prompt change | Mentioned, not wired to CI | **Material gap** |
| Statistical significance on metric movements | Absent | Notable gap |
| Labeled-set growth pattern | Static fixture set | Notable gap |
| Gold signal routed into training data | Not designed; observation-only | **Material gap** |
| A/B framework as first-class | One field; no design | **Material gap** |
| Causality vs correlation discipline | All queries descriptive, no experiments | **Material gap** |
| PDCA with standardize step | No standardize step | **Foundational gap** |
| Andon cord (distributed observation) | Nathan-only | **Foundational gap** |
| Genchi genbutsu (raw-session inspection) | Absent | Notable gap |
| Jidoka (auto-stop on abnormality) | Alerts, no auto-stop | Notable gap |
| Heijunka (pacing) | No discipline | Notable gap |
| 5 whys / root cause | No structure | **Material gap** |
| ADRs (proper depth) | Thin `decisions.jsonl` | **Material gap** |
| Postmortem template + incident library | Absent (matchmaker scope; dispatch has it) | **Material gap** |
| Lessons-learned corpus | Absent | **Foundational gap** |
| Standardize the gain (lint/fixture/invariant) | Not connected | **Foundational gap** |
| Qualitative input channel | Absent | **Material gap** |
| User-submitted output feedback | Implicit in `dismiss_reason`, no channel | Notable gap |
| Unit economics | Token cost only, no aggregation | Notable gap |
| Meta-loop on kaizen itself | Absent | **Foundational gap** |
| Multi-subject support | Matchmaker-only | **Foundational gap** |

Five foundational gaps; eight material gaps; six notable gaps. **The sketch is a credible weekly-review for one subject. It is not yet an observation-and-improvement system for the estate.** That is the honest comparison.

### 2.1 The single biggest miss

If only one item could change: **the missing Standardize step**. Without it, every kaizen cycle is an isolated event. The lesson does not get encoded into a regression guard, a fixture, an invariant, or a checklist. Six months later, a new prompt version reintroduces the fabrication pattern that v2 was demoted for, and we only catch it on the *next* weekly review — having paid the user-trust cost in the interim.

The Standardize step is the only thing that turns a kaizen loop into a *compounding* moat versus a treadmill.

### 2.2 The second biggest miss

**Sphere-siloed thinking.** The sketch designs the counting-room around matchmaker. If matchmaker quality drops, the sketch cannot ask: was this caused by a chatbot rollout that confused users? A docs personalisation change that mis-set expectations? A dispatch agent that broke an upstream producer? Without cross-sphere correlation as a first-class concern, every problem will look local.

---

## §3 Registry architecture — the answer to "by project? by agent?"

**Both, plus cross-cutting.** The right shape is a three-level registry.

### 3.1 Level 1 — Subject registry (root)

A single `subjects.yaml` at the root of the counting-room repo (or wherever the kaizen system lives — see §6). Each subject is a thing being observed:

```yaml
version: 1
subjects:
  - id: ghp-matchmaker
    project: aigranthelper
    agent: matchmaker
    sphere: customer
    owner: nathan
    review_cadence: weekly
    contract: subjects/ghp-matchmaker/contract.yaml
    status: active

  - id: ghp-chatbot
    project: aigranthelper
    agent: chatbot
    sphere: service
    owner: nathan
    review_cadence: weekly
    contract: subjects/ghp-chatbot/contract.yaml
    status: planned  # not yet built; placeholder

  - id: ghp-alerts
    project: aigranthelper
    agent: alert-generator
    sphere: customer
    owner: nathan
    review_cadence: weekly
    contract: subjects/ghp-alerts/contract.yaml
    status: planned

  - id: dispatch
    project: oversteward
    agent: pickup-playbook
    sphere: internal
    owner: nathan
    review_cadence: monthly
    contract: subjects/dispatch/contract.yaml
    status: active

  - id: grantspider-crawler
    project: grantspider
    agent: crawler
    sphere: internal
    owner: nathan
    review_cadence: monthly
    contract: subjects/grantspider-crawler/contract.yaml
    status: active

  - id: research-drift
    project: aigranthelper
    agent: drift-check
    sphere: internal
    owner: nathan
    review_cadence: monthly
    contract: subjects/research-drift/contract.yaml
    status: active

  - id: docs-personalize
    project: aigranthelper
    agent: docs-personalize
    sphere: docs
    owner: nathan
    review_cadence: monthly
    contract: subjects/docs-personalize/contract.yaml
    status: planned
```

The `(project, agent)` pair makes the answer to Nathan's question concrete: **each subject is keyed by project AND agent**. Both registries (by-project, by-agent) are derived views over the same table. `subjects.yaml` is the source.

Adding a fifth sphere subject is a `subjects.yaml` entry plus a contract file. Nothing in the analysis code knows or cares about sphere boundaries; the queries traverse subjects.

### 3.2 Level 2 — Per-subject contracts

```
subjects/
  ghp-matchmaker/
    contract.yaml           # telemetry schema reference, sla, owner, etc.
    queries.yaml            # subject-specific queries (Q1-Q8 for matchmaker)
    rubrics.yaml            # link to prompts/matchmaker/quality-rubric@v1
    thresholds.yaml         # subject-specific anomaly thresholds
    review.qmd              # Quarto template for this subject's review
    fixtures/               # canonical test data
  ghp-chatbot/
    contract.yaml
    queries.yaml            # CSAT, time-to-resolution, escalation rate, ...
    rubrics.yaml
    thresholds.yaml
    review.qmd
    fixtures/
  dispatch/
    contract.yaml           # already implicit in pipeline_history.jsonl
    queries.yaml            # dispatch cycle time, refusal rate, harness-drop rate, ...
    thresholds.yaml
    review.qmd
    fixtures/
  ...
```

Per-subject contract carries the telemetry schema, the SLA, who owns it, what review cadence applies, and which queries / rubrics / fixtures are active for it.

### 3.3 Level 3 — Cross-cutting (the lessons corpus + decision/postmortem libraries)

```
shared/
  lessons.jsonl             # kaizen knowledge base; tagged by subject(s)
  decisions/                # ADRs, one markdown per decision (not jsonl — too thin)
    YYYY-MM-DD-{slug}.md
  postmortems/              # incident library
    YYYY-MM-DD-{slug}.md
  experiments/              # A/B framework registry
    YYYY-MM-DD-{slug}.yaml
  invariants.yaml           # standardize-the-gain — invariants every subject must honour
```

The lessons corpus is **the load-bearing piece** missing from the original sketch. Every kaizen cycle ends in one row of `lessons.jsonl`:

```json
{
  "id": "lesson_2026_05_19_001",
  "ts": "2026-05-19T...",
  "subjects": ["ghp-matchmaker"],
  "origin": {"review_id": "matchmaker-weekly-2026-05-19", "section": 3},
  "principle": "Explanation prompts must enforce citation-per-claim at validation time, not at rubric time. Catching a fabrication in the rubric is one cycle too late; catching it at output validation prevents it shipping.",
  "rationale": "v2 fabrications all passed structural output validation because validation only checked schema, not claim-citation alignment. Rubric caught it after users had already seen it.",
  "standardize": [
    {"kind": "fixture", "ref": "prompts/matchmaker/explanation@v1.fixtures.json#adversarial-fabrication-probe"},
    {"kind": "invariant", "ref": "shared/invariants.yaml#I-MM-1"},
    {"kind": "validator", "ref": "src/matchmaker/validate.py:check_claim_citation_alignment"},
    {"kind": "review-section", "ref": "subjects/ghp-matchmaker/review.qmd#fabrication-watch"}
  ],
  "cross_subject_applicability": ["ghp-chatbot", "docs-personalize"],
  "verified_at": null,
  "verified_outcome": null
}
```

This row says: we learned a thing, here is the principle phrased durably, here are the four places it has been encoded so it cannot be lost, and these other subjects have the same failure mode and should adopt the same standardize-pattern.

The `cross_subject_applicability` field is what makes this an estate-wide kaizen system rather than a per-subject one. Every lesson gets reviewed at promotion time against the other active subjects.

### 3.4 Schema discipline across the three levels

`subjects.yaml` is structured config. Per-subject `contract.yaml` carries a `schema_version` and a reference to the Pydantic model. `lessons.jsonl`, `decisions/*.md`, `postmortems/*.md` follow ADR-style templates. The contract for each level is in version control; promotions to any level land via PR with reviewable diff.

---

## §4 The PDCA cycle, made concrete

PDCA-with-Standardize, mapped to the artifacts the system produces.

| Step | Artifact | Where |
|---|---|---|
| **Plan** — observation produces a hypothesis | Promotion candidate in §6 of subject review | `subjects/{id}/reviews/YYYY-MM-DD.html` |
| **Do** — change is made (prompt promotion, code change, config edit) | PR + `decisions/YYYY-MM-DD-{slug}.md` ADR | `shared/decisions/` |
| **Check** — measure impact at +1 week, +4 weeks | Next reviews; query joins on `decisions.implemented_at` | `subjects/{id}/reviews/...` |
| **Standardize** — encode the lesson | `lessons.jsonl` row + fixture/invariant/validator/review-section refs | `shared/lessons.jsonl` + the four encoded targets |
| **Act-again** — propagate to other subjects | `lessons.jsonl.cross_subject_applicability` triggers review of sibling subjects | sibling subject reviews |

The Standardize step is non-optional. A promotion that did not produce a `lessons.jsonl` row is an incomplete kaizen cycle and is flagged in the weekly review's §7 ops summary.

---

## §5 Foundational additions to the sketch

Beyond §3's registry, these are the missing primitives.

### 5.1 Andon cord — distributed observation
A single low-friction channel where anyone (Nathan, a future analyst persona, an automated check, an end user) can flag an issue. Implementation: a `gh issue` template on the appropriate repo, with the `andon` label, that auto-files into a `shared/andon.jsonl` log read by every subject's weekly review.

### 5.2 Genchi genbutsu — raw-session inspection
The Monday review opens with §1 aggregate health. Once a month (or whenever an anomaly fires), Nathan opens **three random raw run-id sessions** end-to-end — every telemetry row, every prompt output, every user follow-up. Aggregate views hide the texture; raw inspection reveals it. The notebook surfaces three sampled session ids in §0 (pre-aggregate).

### 5.3 Jidoka — auto-stop on abnormality
When a metric breaches a hard threshold, the system does not just alert — it **auto-reverts the offending change** if the change can be tied to the breach. Example: prompt version v{n+1} promoted on Tuesday, fabrication rate breached on Thursday → auto-pin back to v{n} and file an andon. Configurable in `thresholds.yaml`; off by default until trust is established.

### 5.4 Statistical discipline
Every recommendation in §6 carries a confidence interval. The recommender refuses to recommend when N is too small. A "no recommendation this week, sample size insufficient" outcome is honourable and frequently the right answer.

### 5.5 Experiment framework
`shared/experiments/` holds the registry. Every promotion that *can* be A/B tested *is* — assignment by user-id hash, holdout fraction declared, success metric pre-registered. Sequential testing rules in the framework. Promotions without an A/B are flagged in §6 of the review as such ("rolled out non-experimentally") so the recommender knows when it cannot make causal claims.

### 5.6 Customer-feedback channel
A structured `/feedback` button on every matchmaker output (and chatbot reply, etc.) that routes into the same telemetry pipeline as the gold signal. New schema row type: `user_feedback` with `(subject_id, output_id, sentiment, free_text_redacted, follow_up_consent)`. The free text passes the §4 PII scrub from matchmaker-instrumentation; consent is opt-in for follow-up interviews.

### 5.7 Postmortem template
Every anomaly that fires an andon spawns a postmortem stub from a template:

```markdown
# Postmortem — {subject_id} / {anomaly} — {date}
## Summary
## Timeline
## Impact (users, dollars, trust)
## Root cause (5 whys)
1. Why did X happen?
2. Why did that condition exist?
3. ...
## Contributing factors
## What went well
## What went poorly
## Action items (each links to an issue + a lessons.jsonl row)
## Lessons (link to lessons.jsonl entries)
```

### 5.8 Lessons-corpus discipline
A row in `lessons.jsonl` is mandatory for every promotion, every postmortem, every quarterly retro. A row carries a `verified_at` + `verified_outcome` field that is null at write time and filled in at the next quarterly retro: did the lesson hold? Did the standardize-encoding actually prevent recurrence?

### 5.9 Unit-economics layer
Aggregations beyond raw token cost:
- $ per match presented
- $ per gold signal earned (B + C signal density / cost)
- $ per active GHP user per week
- $ per fabrication avoided (rubric-cost / fabrications-flagged)

Surfaces in §7 ops of each weekly review. Trends matter more than absolute values at v1.

### 5.10 Meta-review (kaizen on kaizen)
Quarterly review of the kaizen system itself:
- Lead time from observation → promotion → verified outcome
- Promotion success rate (what fraction had the hypothesized effect at +4 weeks)
- Lessons-corpus growth + verification rate
- Andon-cord usage (was the channel used? by whom?)
- Subject coverage (which subjects have not produced a promotion in 90 days — dark, or genuinely stable?)

The quarterly review is itself a subject in `subjects.yaml`, with its own contract, its own queries, its own review cadence.

---

## §6 Where this lives — revising the counting-room shape

The `weekly-review-notebook.md` §4 recommendation was: separate repo, name `the-counting-room`, matchmaker-only scope. **The redesign keeps the separate-repo recommendation but expands the scope.** The counting-room is the home for the *whole* kaizen system, not just matchmaker.

Revised repo layout:

```
the-counting-room/
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── _quarto.yml
├── subjects.yaml                       # root subject registry (§3.1)
├── subjects/
│   ├── ghp-matchmaker/                  # one directory per active subject
│   ├── ghp-chatbot/                     # placeholder for planned subjects
│   ├── dispatch/
│   ├── grantspider-crawler/
│   ├── research-drift/
│   ├── docs-personalize/                # placeholder
│   └── kaizen-meta/                     # the quarterly review subject
├── shared/
│   ├── lessons.jsonl                    # cross-cutting kaizen corpus
│   ├── decisions/                       # ADRs
│   ├── postmortems/                     # incident library
│   ├── experiments/                     # A/B framework registry
│   ├── andon.jsonl                      # distributed observation channel
│   └── invariants.yaml                  # standardize-the-gain
├── src/the_counting_room/
│   ├── loaders.py                       # multi-source telemetry loaders
│   ├── queries/
│   │   ├── matchmaker/                  # subject-scoped query modules
│   │   ├── dispatch/
│   │   ├── crawler/
│   │   └── _registry.py                 # binds subjects' queries.yaml to functions
│   ├── narrators.py
│   ├── charts.py
│   ├── recommenders/                    # per-subject + cross-subject recommenders
│   ├── statistics.py                    # confidence-interval helpers; sequential testing
│   ├── experiments.py                   # A/B assignment + analysis
│   ├── delivery/
│   ├── andon.py                         # distributed observation channel
│   ├── meta.py                          # kaizen-on-kaizen quarterly review logic
│   └── schemas.py                       # all subject schemas, versioned
├── config/
│   ├── thresholds.yaml                  # global anomaly thresholds (overridden per subject)
│   ├── delivery.yaml
│   └── auto_revert.yaml                 # Jidoka rules — disabled by default
├── prompts/
│   ├── review/
│   │   ├── narrate-anomaly@v1.md        # if rules-narration falls back to LLM
│   │   └── 5-whys-prompt@v1.md          # postmortem assistant prompt
│   └── meta/
│       └── lesson-distil@v1.md          # helps phrase a lesson durably from a promotion
├── notebooks/
│   ├── weekly/                          # one .qmd per subject
│   ├── monthly/
│   ├── quarterly-meta.qmd
│   └── ad-hoc/
├── tests/
│   ├── test_loaders.py
│   ├── test_queries.py
│   ├── test_recommenders.py
│   ├── test_statistics.py
│   └── fixtures/
├── .github/workflows/
│   ├── weekly-review.yml
│   ├── monthly-review.yml
│   ├── quarterly-meta.yml
│   └── ci.yml
└── Makefile
```

This is a real platform, not a weekly notebook. The build-cost ballpark from `weekly-review-notebook.md` §4.8 (16-23 hours for v1) **was wrong as scoped**; it covered matchmaker-only with no kaizen primitives. The honest revised estimate, for a v1 covering matchmaker + dispatch (two subjects, both of which already emit telemetry today) + the kaizen primitives (lessons corpus, ADR template, postmortem template, andon channel, basic statistical discipline) is **40-60 hours**. That is real engineering effort, not a notebook.

The right alternative for very-near-term-Nathan: ship a **minimum kaizen surface** (subject registry + lessons corpus + ADR template + andon issue label) before the counting-room scaffolds. Even without any analysis code, those artifacts existing prevents the cycle from leaking knowledge. Cost: 2-4 hours of doc + template authoring.

---

## §7 What Nathan is missing — the answer to the specific ask

Pulling together the diagnoses into a direct answer to "what am I missing here?"

1. **The Standardize step.** Every other kaizen system primitive depends on this one. Without it, every promotion is an isolated event and the moat does not actually compound — it just gets re-paved.
2. **Cross-subject correlation.** Failure modes are rarely isolated to one sphere. Designing for a single subject locks in a blind spot.
3. **The lessons corpus** as a first-class artifact distinct from decisions and postmortems. Decisions record choices; postmortems record incidents; lessons record principles. The three are not interchangeable.
4. **Andon-cord channel** for distributed observation. Even today, "Nathan-only" misses the cases where Nathan-in-session-A would have noticed something that Nathan-in-session-B forgot.
5. **Causality discipline.** A descriptive query is not a causal claim. The recommender that turns observation into action must distinguish them or it will routinely promote on noise.
6. **The Standardize-encoding targets** — where a lesson lands. Four canonical homes (fixture, invariant, validator, review-section) so the lesson is encoded in code, not only in memory.
7. **The meta-loop.** The kaizen system needs its own kaizen cycle. Without it, the system becomes the thing it was built to prevent — a frozen process that drifts from reality.
8. **Postmortem template + 5-whys discipline.** Without structure, root-cause analysis collapses into "v2 prompt was the cause," which is level 1 of 5 and stops far short of the systemic cause.
9. **Customer-feedback channel as first-class telemetry.** What users *think* is not the same as what they *did*. A behavioural-only system misses the qualitative signal.
10. **Unit economics.** The firmware can compound in quality while regressing in economics. Without $/outcome tracking, the trajectory is unknown.

---

## §8 Revised recommendation — sequenced

In order, smallest-thing-first:

1. **Author the minimum kaizen surface in oversteward** (2-4 hours total):
   - `subjects.yaml` at oversteward root with the active subjects today (matchmaker-planned, dispatch-active, grantspider-crawler-active, research-drift-active).
   - `documentation/decisions/` directory with one ADR template + the existing major decisions backfilled (the dispatch retirement, the in-session-default flip, the cross-DB cutover, the ontology surface ship).
   - `documentation/lessons.jsonl` seeded from the most-load-bearing `feedback_*` memory entries (5-10 rows).
   - `documentation/invariants.yaml` — extracted from `architecture.md` §3 invariants table (this is the standardize-the-gain home that already exists; formalize the file).
   - `andon` label on each pickup repo + a one-page issue template.

2. **Scaffold the counting-room repo** (covers §6 layout), but with **only** the matchmaker subject's `subjects/ghp-matchmaker/` populated. Plus the cross-cutting shared/ directory wired up. Run a `make weekly-review` end-to-end against fixture data to prove the stack. (16-23 hours, the original sketch estimate, now scoped correctly to one subject.)

3. **Add the dispatch subject** (4-8 hours). Reuses the same loader, queries, narrators, charts, delivery. Proves the multi-subject design works.

4. **Add the andon-cord ingestion** (2-3 hours). Read `shared/andon.jsonl` (or the GH `andon` label across all dispatch-target repos) and surface in every subject's weekly review pre-aggregate.

5. **Add the statistical layer** (4-6 hours). Confidence intervals on every recommendation; "insufficient sample" abstain path.

6. **Add the experiment framework** (8-12 hours). `shared/experiments/` registry, assignment by user-hash, sequential testing, post-experiment analysis cell in the relevant subject's review.

7. **Quarterly-meta subject** (4-6 hours). The kaizen-on-kaizen review running on a 90-day cadence against `lessons.jsonl`, `decisions/`, `postmortems/`, and subject coverage.

Total revised v1 cost: **40-60 hours**, sequenced over weeks. The first step (the minimum kaizen surface in oversteward) **is the highest leverage and the cheapest** — even if the counting-room never ships, that surface alone changes the kaizen posture from "informal" to "structured."

---

## §9 Open questions — RESOLVED 2026-05-14

All five questions answered by Nathan; resolutions recorded here. Implementation landed in the Fiscus genesis commit ([fiscus@fd6a4c4](file:///c:/Users/natha/OneDrive/Tech/Python/Fiscus/)) and in [shared/decisions/2026-05-14-0001-fiscus-genesis.md](file:///c:/Users/natha/OneDrive/Tech/Python/Fiscus/shared/decisions/2026-05-14-0001-fiscus-genesis.md).

1. ~~**Multi-subject scope ambition or premature?**~~ → **Multi-subject is the correct ambition. Build it that way from the foundation.** Foundational gaps in §2 (sphere-siloed thinking, cross-subject correlation) are not refactorable cheaply; designing for the right shape now is the correct trade-off.
2. ~~**Where does `subjects.yaml` live?**~~ → **In a new project called Fiscus** (Latin: *imperial treasury*; "our learning is our treasure"). Fiscus is its own repo, peer to oversteward and aigranthelper. Not a tenant of oversteward — different concern (product observability vs development governance).
3. ~~**Lessons corpus ownership?**~~ → **In Fiscus** (`shared/lessons.jsonl`), seeded from oversteward `feedback_*` memory entries. Future memory writes that name a lesson get carried over.
4. ~~**Andon channel concrete form?**~~ → **GH `andon` issue label per repo**, aggregated nightly into `Fiscus/shared/andon.jsonl` by `src/fiscus/andon.py`. Issue template at `.github/ISSUE_TEMPLATE/andon.md` in each pickup repo (template lives in Fiscus as the canonical version).
5. ~~**Customer-feedback channel timing?**~~ → **Matchmaker stub in Fiscus today** (`subjects/ghp-matchmaker/contract.yaml` references `user_feedback` event type). Two AG issues filed for the implementation: [aigranthelper#514](https://github.com/NathanKrupa/aigranthelper/issues/514) (feedback button on matchmaker outputs) and [aigranthelper#515](https://github.com/NathanKrupa/aigranthelper/issues/515) (general-usage telemetry endpoint + Fiscus pull authentication). Continuous improvement spans the whole AG product, not only matchmaker.

**Bonus resolution (Nathan's directive 6):** local testing + linting from day one — gaudi (pre-commit + CI), ruff, pyright, pytest, plus the boy-scout rule enforced in CI via `scripts/boy_scout_check.py` and the promotion-lesson check (invariant I-F-1) via `scripts/promotion_lesson_check.py`. Live in Fiscus from the genesis commit.

**Bonus resolution (Nathan's directive 3):** Fiscus observes Fiscus. `subjects/fiscus-meta/` is a real subject with quarterly cadence; one lesson must land against Fiscus per quarter. Codified as invariant I-F-6 in `Fiscus/shared/invariants.yaml`.

---

## §10 What stays true

Two things from the original sketch survive the critique intact:

1. **The counting-room as a separate repo from aigranthelper and oversteward.** That decision was right; the redesign expands its scope but does not change its home.
2. **Working backwards from the Monday-morning artifact.** The discipline of designing what gets read before what gets built remains correct. The redesign just adds more readers (per-subject reviews, monthly, quarterly-meta) and more pre-aggregate content (sampled raw sessions, andon items, lesson-verification status).

The sketch is salvageable. It is also incomplete. This document is the honest accounting of which is which.

*Last updated: 2026-05-13 (v0 — diplomatically-honest critique + redesign of weekly-review-notebook.md §4 scope).*
