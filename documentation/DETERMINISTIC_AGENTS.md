ABOUTME: Blueprint for the deterministic workflow agents the House of Krupa needs, anchored on Grant Helper Pro.
ABOUTME: Four spheres × design-first-plus-capture-first synthesis. Workflow is the moat; the model is the chip.

# Deterministic Agents — Blueprint

> **Working thesis.** Frontier LLM capability is commoditizing for most production tasks. The defensible IP is not "we use Claude" — it is the *workflow* around the model: the sequence of steps, the guards at each step, the prompts refined through hundreds of failures, the structured outputs and the schemas they fit into, the evaluation rubrics, and the edge cases instrumented into checks. Workflows compound; models do not.
>
> Useful frame: **the model is the chip, the workflow is the firmware, the product is the appliance.** Chips commoditize. Firmware accumulates. Appliances win markets. Grant Helper Pro's defensibility lives in the firmware layer.

This document is the blueprint for that firmware. It is anchored on **Grant Helper Pro** because that is where the IP matters most and where user behaviour is observable. The other House of Krupa repos (aigranthelper, grantspider, wphelper, ai-assistants, oversteward) supply infrastructure; GHP is where it earns its keep.

---

## §1 What "deterministic agent" means here

A deterministic agent is one whose behaviour is constrained by:

1. **A typed contract.** Named inputs, structured outputs, validated against a schema. No prose-only returns. The dispatch playbook's "structured YAML final report" is the in-house exemplar — every run terminates in `final_state ∈ enum` plus a fixed payload.
2. **Idempotent steps.** Re-running with the same inputs either no-ops or produces the same result. State is read before it is written. Idempotency keys (a label, a branch name, a record id, a content hash) make this enforceable.
3. **Instrumentation by default.** Every step emits structured telemetry: inputs (hashed/redacted as needed), outputs, latency, model used, token cost, success/failure, and — critically — *what the user did next*. The telemetry is the raw material for §3's feedback loop.
4. **Swappable intelligence layer.** Prompts and evaluation rubrics live in version-controlled config, not in source. The "intelligence layer" can iterate without redeploying the workflow.
5. **Kill-switches and structured refusals.** A label, a config flag, a dry-run mode, and a refusal path that emits a *structured* reason rather than freestyling a workaround.

These five properties apply across all four spheres. The sphere determines the audience and the surface; the properties are universal.

---

## §2 The four spheres

The carve-up of GHP-and-adjacent agent work:

| # | Sphere | What lives here (GHP-anchored) | Reliability bar | Learning loop |
|---|---|---|---|---|
| 1 | Customer-facing GHP workflows | Matchmaker (flagship), profile builder, match refresh, alert generation | Highest — wrong output costs the customer money or trust | Rich — every click, dismiss, save, application is a labelled signal |
| 2 | Internal / DevOps | Crawler health (grantspider), DB integrity (drift checks), lead-activation reminders, dispatch playbook (already shipped) | High — wrong output corrupts the data layer everyone depends on | Bounded — failure modes are well-known, recovery is human-driven |
| 3 | Customer service | AI chatbot for GHP users — onboarding, troubleshooting, grant-writing help, billing context | Medium — wrong answer is recoverable; bad tone is a brand cost | Rich, but lagging — needs Sphere 1 in production first to know what users actually ask |
| 4 | Documentation | AI-assisted generation, maintenance, and personalization of GHP docs (and downstream of that, internal docs) | Low to medium — wrong docs degrade trust over time but rarely break a customer | Lagging — best content emerges from observed Sphere 1 + 3 failure modes |

The four are not equal-weight by *value*, by *risk*, or by *build order*. See §6 for the recommended sequence. Spheres 1 and 2 can run in parallel; Spheres 3 and 4 are explicitly downstream of Sphere 1 having shipped and produced telemetry.

---

## §3 The synthesis — design-first AND capture-first

Two postures most people argue between:

- **Design-first.** Lay out the workflow at the outset — schemas, idempotency keys, retry policies, observability. *Risk: you ossify around guesses about how users will interact with the tool, and miss the actual patterns.*
- **Capture-first (analysis layer).** Watch real users; codify what they actually do; find the value-creating workflows that 5% of power users invent. *Risk: you fly blind for months before you have enough data to learn anything.*

You need both, but they serve different time horizons. The synthesis, in five moves:

### 3.1 Design the skeleton deterministically

Lock the named steps, the schemas, the guards, the idempotency. **You cannot capture data on a workflow that doesn't exist yet.** The first version has to be designed. For high-stakes paths (sending an email to a foundation, charging a customer, modifying a foundation record), "we'll figure it out as we go" is malpractice.

Concretely for an agent: define the step list, give every step a name, define the input/output schema for each step, and decide what each step's idempotency key is.

### 3.2 Instrument every step from day one

Each named step emits structured telemetry: inputs (hashed/redacted as needed), outputs, latency, model used, token cost, success/failure, the prompt/rubric version used, and *what the user did next*. The "what the user did next" field is the gold — it's what turns a step's output from "did the model respond?" into "did the response create value?"

The telemetry home is `data/pipeline_history.jsonl` for the orchestration sphere already; extend it to other spheres rather than spawning per-agent log files.

### 3.3 Make prompts and rubrics swappable, not hardcoded

Prompts live in version-controlled config (a `prompts/` directory or similar), not embedded in source. Same for evaluation rubrics. This means the intelligence layer can iterate without redeploying the workflow — the firmware updates without re-flashing the chip. It also means a prompt change is a *reviewable diff* with a clear blame trail, not a hidden string buried in business logic.

### 3.4 Build the feedback layer separate from the workflow itself

The feedback layer runs *over* captured telemetry, not inside the request path. Patterns it surfaces:

- Which steps fail most often, and why?
- Where do users abandon?
- Which prompts produce low-quality outputs (by automated rubric or by user signal)?
- What are users *trying* to do that the workflow doesn't yet support?
- Which deterministic paths are users routing around with manual workarounds?

A thin v1 of the feedback layer is a weekly SQL query over telemetry, reviewed by Nathan. That is already better than 90% of what gets called "AI product analytics" in this market.

### 3.5 Promote learnings back into the design

A weekly or monthly cadence where insights from the feedback layer become workflow changes, prompt updates, or new steps. **This is where the IP actually accumulates.** Every iteration adds to the moat. Every nonprofit using GHP makes the flywheel spin faster for every other nonprofit using GHP — but only if the loop exists to harvest the data.

The capture itself never stops. The skeleton is designed once; the prompts, rubrics, weights, and step list are continuously informed by capture.

---

## §4 Sphere I — Customer-facing GHP workflows (the lead)

The flagship sphere. The IP lives here. **This is the sphere that should be designed first**, because (a) the firmware-layer defensibility argument applies most strongly to customer-facing workflows, and (b) the user-behaviour signal is richest here.

### 4.1 Matchmaker (flagship — design lead)

**Deterministic skeleton:**

```
profile intake
  → feature vector construction
    → centroid computation
      → HNSW query
        → top-N retrieval
          → explanation generation
            → presentation to user
```

**Per-step contract (sketch — the next concrete artifact to author):**

| Step | Input schema | Output schema | Idempotency key | Failure mode |
|---|---|---|---|---|
| profile intake | `(user_id, raw_form_payload)` | `ProfileV{n}` typed object + `missing_fields[]` | `(user_id, profile_version_hash)` | partial profile → retry / block |
| feature vector construction | `ProfileV{n}` | `FeatureVector` (dense + sparse) | content hash of profile | feature extraction failure → fail hard |
| centroid computation | `FeatureVector` + `org_history?` | `Centroid` | content hash of inputs | n/a — pure compute |
| HNSW query | `Centroid` + `filters` | `candidate[] (id, distance)` | query plan hash | DB unavailable → retry with backoff |
| top-N retrieval | `candidate[]` | `match[]` enriched with foundation snapshots | `(centroid_hash, N)` | research-DB read fails → soft-fail with last-known cache |
| explanation generation | `match[]` + `ProfileV{n}` | `match[]` with `explanation, confidence, evidence_citations[]` | `(match_id, prompt_version)` | LLM error → ungenerated explanation, not fabricated |
| presentation to user | `match[]` | rendered list + telemetry hooks | n/a (read path) | render error → fall back to ungelled list |

**Instrumentation per step (the part that earns its keep):**
- Inputs (hashed), outputs (typed), latency, model id, prompt version, token cost.
- *What the user did next:* clicked the match (id), dismissed it (id + optional reason), saved it (id), exported / forwarded / applied to it. **The "applied to it" signal is the gold** — it's the only signal grounded in the user's real fundraising work.
- Negative signal: time-on-step, scroll depth, abandonment, return-without-action.

**Analysis layer questions (the feedback loop, §3.4):**
- Are dismissed matches systematically different from saved ones in ways the model isn't capturing?
- Are there profile fields that strongly predict good matches but that 60% of users skip?
- Are there foundations that are matched often but never applied to (mechanically good match, practically wrong)?
- Where does the explanation step produce text users edit before forwarding? That's a prompt-tuning signal.

**Promotion: better feature weights, additional profile prompts, new filtering rules, refined explanation prompts.**

**Capture-first inputs:** what an experienced fundraiser does to find a foundation match, in their own words. This is what AG #432's 41-site inventory begins to surface, but it's not a workflow capture — it's a code inventory. The actual "how does Nathan do this" capture is months of raw material that should land in `documentation/captures/matchmaker.md` before the explanation prompts are tuned.

**Design-first additions (already known, design these in from day one):**
- Evidence-cited output — every match claim has a `property_lineage` provenance citation (already enforced by I-18 / `grantspider.ontology`).
- Confidence scores tied to data freshness (G6 — embeddings staleness).
- Explicit "I don't know / no good match" output when the candidate space is empty. Better to say nothing than to invent.
- Read-only enforcement of `research.*` (I-4) — the matchmaker never writes producer data.

### 4.2 Profile builder

Same skeleton template — capture, intake, validation, store. Idempotency key is profile version hash. Critical instrumentation: which fields users skip and which they fill in; downstream correlation with match quality (does field X predict good matches?).

### 4.3 Match refresh

Triggered by either (a) producer-side data change (new grants in `research.*`) or (b) user-side profile change. Same matchmaker pipeline; the design point is **never re-rank silently** — surface "your matches changed because X" with structured reasons.

### 4.4 Alert generation

Email digests of new matches. Highest blast-radius surface in this sphere — wrong tone or wrong claim costs the relationship. Design-first non-negotiables: never claim a match is a fit without a citation; never fabricate a foundation interest; rate-limit per user; user opt-out is single-click. Capture-first: which alerts get opened, which links get clicked, which users unsubscribe after which alerts.

---

## §5 Sphere II — Internal / DevOps (parallel build)

The most mature sphere today; **runs in parallel with Sphere 1** because it is independent of user behaviour. The dispatch playbook is the reference implementation; every other agent in this sphere should match its structure.

### 5.1 Pickup / dispatch agent (shipped)

`/dispatch <repo> <n>` → 19-step playbook (`.claude/skills/dispatch/playbook.md`) → structured YAML final report → terminal state. Worktree-isolated, harness-dropped detection, baseline-snapshot pattern. **Reference exemplar of all five §1 properties.** In-session pickup is the default mode since 2026-05-06; the dispatch skill itself is queued for retirement (see ROADMAP §4) but its workflow content survives in `documentation/issue-to-pr-workflow.md`.

### 5.2 Drift-check agent (shipped)

`research-drift-check` GH Action on aigranthelper. Detects divergence between consumer's `_generated.py` and producer's pinned schema dump. Required status check on `main` since 2026-05-07. Failure mode is *always* "bump the lock + regenerate in the same PR" — wholly deterministic.

### 5.3 Cross-repo data-contract surface (shipped)

`grantspider.ontology` — typed entities + value types + lineage primitives + walkable relationships, with import-direction lint (I-18). The infrastructure on which Sphere 1's Matchmaker reads its data.

### 5.4 Crawler health agent (unbuilt)

Grantspider runs a crawler that touches external sites. Health monitoring, rate-limit budgets, freshness-of-corpus checks. Telemetry: per-source freshness, per-source error rate, per-source SLA breach (G2 — operator surface for SLA-breaching sources). Promotion: which sources get prioritized for re-crawl, which get demoted, which get pulled.

### 5.5 DB integrity agent (unbuilt — partly subsumed by drift-check)

Cross-table invariants beyond what the schema enforces. Example: every `Foundation` with `last_filing_year > 0` must have at least one `Filing` in `research.filings`. Reports orphan rows, negative-cardinality-mismatch rows, snapshot-vs-cache divergence. Failure mode: report-only by default; never auto-repair without explicit Nathan approval.

### 5.6 Lead-activation reminder agent (unbuilt)

Internal-DevOps even though it nudges the human (Nathan). Watches the consulting-funnel state machine; reminds Nathan when a lead has been inactive for N days at stage X. Idempotency key is `(lead_id, stage, last_action_ts)`. Never auto-emails the lead — only nudges Nathan.

### 5.7 Sweeper / drain agents (open issues #2 and #3)

Predate the in-session pickup default; rescope before building. Issue #2 (sweeper for stuck `agent-in-progress` labels) → manual `/sweep-stuck-labels` skill. Issue #3 (drain queue) → session-pickup checklist rather than autopilot.

---

## §6 Sphere III — Customer service (downstream of Sphere I telemetry)

**Built after Sphere I has shipped enough Matchmaker telemetry to know what users actually ask.** Building this earlier produces a chatbot trained on imagined questions rather than real ones.

### 6.1 GHP user chatbot

Onboarding ("how do I set up my org profile?"), troubleshooting ("why didn't I get any matches?"), grant-writing help ("how do I write the program description for this RFP?"), billing context ("what's on my invoice?"). Each is a different deterministic skeleton — they share the chat surface but not the step list.

**Design-first non-negotiables:**
- Bot never sends outbound on the user's behalf.
- Bot never invents a foundation fact (every claim cites the same `property_lineage` provenance the Matchmaker uses).
- Bot has a "I'd better get a human" route that is a single config flag away from being live; the route fires whenever confidence drops below threshold or when the user types stress-signals ("I'm losing my mind", "this is broken", "speak to someone").

**Capture-first inputs:** Sphere I's Matchmaker telemetry, especially the "what did the user do after dismissing this match" field. The questions users *would* ask the chatbot are visible in the abandonment paths today.

### 6.2 Inbound triage agent (Almoner consulting + GHP support)

Mailbox poll → triage → draft. Outputs: `{category: enum, draft_reply: string|null, escalate: bool, suggested_label: string}`. Never sends — only drafts.

**Capture-first prerequisite:** Nathan's existing inbox routine — what he reads, what he categorizes, what he replies to vs files vs archives. This capture is the work; without it, the agent designs against a fantasy. Lives at `documentation/captures/inbox-triage.md` when authored.

---

## §7 Sphere IV — Documentation (downstream of Sphere I + III)

**Built last because the best docs emerge from observed failure modes, not from speculation about what users need to know.**

### 7.1 GHP docs generation

Generated from real Sphere I user questions + Sphere III chatbot fall-throughs. The corpus of "what 100 users actually got confused about" is the source material. Without that corpus, generated docs are imagined-user docs.

### 7.2 Personalization

Same docs, rendered against the user's profile. "Your org is small, so this section about indirect-cost rate caps doesn't apply to you." Designed-first non-negotiables: personalization never hides legally-required information; never hides information that would make the user a better grant applicant in the long run, even if it doesn't apply to the *current* match.

### 7.3 Internal docs (already partly running)

Per-repo pickup-context docs (`documentation/repos/*.md` — directory exists, mostly empty). Architecture maintenance (`architecture.md` — pull-based). ROADMAP / SESSION_STATE / Stewards_Ledger. These run on capture-first discipline today; future agent could lint citations + flag stale rows for re-verification.

---

## §8 Cross-cutting concerns

### 8.1 Single telemetry home

`data/pipeline_history.jsonl` is the existing JSONL audit log for the orchestration sphere. Extend it as the universal log — add a `sphere` field, an `agent` field, and per-agent payload. One queryable home is worth more than per-agent log silos.

### 8.2 Prompt and rubric versioning

Every prompt and every evaluation rubric carries a version. Telemetry rows record the version that was active for the run. Promotion (§3.5) is a version bump with a reviewable diff; rollback is a version pin in config.

### 8.3 Kill-switch convention

Every agent has: a label or config flag that disables it (`dispatch-paused` is the existing pattern), a dry-run mode (`--report-only` for sow.py is the existing pattern), and a refusal path that emits a structured reason rather than freestyles a workaround (`final_state: REFUSED_PREFLIGHT`).

### 8.4 Layer discipline

Per `~/.claude/CLAUDE.md` and `architecture-principles.md`: outer = thin entry point (skill / view / webhook). Middle = the real work, lives in `src/` once extracted. Inner = one connector, one external system. `wphelper` is the canonical connector home (I-9). The matchmaker's outer layer is a Django view; its middle layer is the matching service; its inner layer is the `ag_research_reader` connector.

### 8.5 Capture-first discipline

For every Sphere I-III workflow, before the skeleton is locked: a markdown capture in `documentation/captures/<sphere>/<workflow>.md`. Authored by Nathan, in his own words. Steps, inputs, outputs, edge cases, "what makes a good outcome." The dispatch playbook works because it was captured first; the matchmaker will work for the same reason.

### 8.6 Forcing-function gates

Several agents on this list are explicitly *not* built yet, gated on a real-world trigger:
- **Customer service chatbot (§6.1)** — gated on Sphere I producing enough Matchmaker telemetry to ground prompt design.
- **Documentation generation (§7.1)** — gated on Sphere I + III producing observed failure modes.
- **Sow agent (governance)** — gated on a sync task manual workflow can't absorb (H2-5).

These gates are part of the design — building before the gate fires produces speculative work.

---

## §9 What to build next (recommended sequence)

Ordered by leverage and capture-readiness.

1. **Matchmaker instrumentation schema** (Sphere I, the lead). Even before any new code: a typed schema for the per-step telemetry rows the Matchmaker emits. This is the cheapest thing to get right at the outset and the most expensive to retrofit. Lives at `documentation/captures/matchmaker-instrumentation.md` or similar. **Offered as concrete next artifact in §10.**
2. **Matchmaker skeleton + step contracts.** Per-step input/output schemas, idempotency keys, failure modes. Filled-in version of §4.1's table. Lock these before writing the explanation prompts.
3. **Sphere II in parallel: crawler health, DB integrity.** Independent of user behaviour; failure modes are well-known; can start while Sphere I instrumentation is being designed.
4. **Sphere I lead: ship the Matchmaker against the locked skeleton + instrumented from day one.** Prompts and rubrics in version-controlled config from the first deploy — never in source.
5. **Feedback-layer v1: weekly SQL over telemetry, reviewed by Nathan.** No fancy dashboard; a notebook with the questions in §4.1's analysis layer is enough to start.
6. **First promotion cycle.** Take one observation from the weekly review and turn it into a prompt/rubric/weight change. Document it. This is the moment the firmware starts compounding.
7. **Sphere III chatbot v1** — only after Sphere I has 4-6 weeks of production telemetry. Built against the captured questions, not imagined ones.
8. **Sphere IV docs personalization** — only after Sphere III has surfaced the failure-mode corpus.

Internal/DevOps maintenance (existing dispatch lineage, drift-check, ontology surface) continues alongside this list — it does not block any of it.

---

## §10 Artifacts landed

The blueprint above is supported by these concrete design v0 artifacts in oversteward:

- **[captures/matchmaker-instrumentation.md](captures/matchmaker-instrumentation.md)** — the full per-step telemetry schema (envelope + 8 step payloads + redaction rules), with eight standing analysis-layer queries that prove the schema can answer §3.4's questions.
- **[captures/gold-signal-ingestion.md](captures/gold-signal-ingestion.md)** — the three ingestion paths that populate `applied_to_external_signal` (Kit email click, export download, manual self-report), with mapping logic, idempotency rules, failure modes, and the `run_id: null` exception for self-report.
- **[prompts/README.md](prompts/README.md)** — registry conventions (versioning, file structure, substitution rules, output-contract validation, promotion workflow, active-version pointer).
- **[prompts/matchmaker/explanation@v1.md](prompts/matchmaker/explanation@v1.md)** — the generation prompt for §4.1's explanation step, with input/output schemas, refusal patterns, and six canonical test fixtures.
- **[prompts/matchmaker/quality-rubric@v1.md](prompts/matchmaker/quality-rubric@v1.md)** — the LLM-as-judge rubric scoring explanations across five dimensions (provenance, specificity, tone, calibration, refusal), with a `fabrication_flag` that forces a provenance demotion.
- **[captures/weekly-review-notebook.md](captures/weekly-review-notebook.md)** — the Monday-morning matchmaker review (target output + tool stack worked-backwards). The matchmaker-only scope in this doc's §4 is superseded by the kaizen architecture below.
- **[captures/kaizen-architecture.md](captures/kaizen-architecture.md)** — diplomatically-honest critique of the weekly-review sketch against best practice (three observation pillars, eval-driven dev, closed-loop feedback, experimentation, PDCA with Standardize step, andon cord, lessons corpus, unit economics, meta-loop). Proposes a multi-subject registry (per-project AND per-agent), the missing Standardize-the-gain step, and an expanded counting-room scope covering matchmaker + dispatch + crawler + drift + (planned) chatbot + docs-personalize + a kaizen-on-kaizen quarterly review. Five foundational gaps, eight material gaps, six notable gaps named explicitly.

Next concrete step when implementation begins: lock the `MatchmakerEvent` Pydantic models matching the envelope and payloads in matchmaker-instrumentation §3/§5, then ship Path B from gold-signal-ingestion (`export_downloaded`) as the v1 floor — internal-only, no external systems, lowest risk. The counting-room sidecar can be scaffolded ahead of any real telemetry by running against synthetic fixtures from matchmaker-instrumentation §5.

---

## §11 Maintenance

Update this doc when:
- A new agent ships (move it from "unbuilt" to "shipped" with a PR citation).
- An agent's contract changes (update the §X.Y contract row).
- A capture document lands (cite it in the relevant agent entry).
- The four-sphere model proves wrong — the spheres are a working hypothesis, not a fixed taxonomy. If reality clusters differently, restructure rather than force-fit.

If §4-§7 grow past readable length, split per-sphere into separate docs and keep this as the index.

*Last updated: 2026-05-07 (post-chat synthesis: workflow-as-IP thesis, GHP-anchored four-sphere model, Matchmaker as design lead, instrumentation-from-day-one).*
