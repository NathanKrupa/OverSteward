ABOUTME: The Monday-morning matchmaker review — working backwards from the output Nathan reads to the tools that produce it.
ABOUTME: Also answers: does the analysis-layer infrastructure live in oversteward, in aigranthelper, or in its own project?

# Weekly Review — Notebook Sketch

**Companion to:** [matchmaker-instrumentation.md](matchmaker-instrumentation.md), [gold-signal-ingestion.md](gold-signal-ingestion.md), [DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §3.4.
**Status:** v0 — design sketch, no notebook yet. **§4's scope (matchmaker-only) is superseded by [kaizen-architecture.md](kaizen-architecture.md), which interrogates this sketch against best practice and expands the counting-room into a multi-subject kaizen platform.** This document survives as the Monday-morning artifact target; the registry and standardize-step structure live in the kaizen-architecture doc.
**Authoritative for:** what the Monday-morning matchmaker review report looks like, what tools produce each section, and (in §4, now superseded) the initial counting-room shape.

> The big vision is locked. This document is about the cogs and gears that make the review *run on Sunday night and land in Nathan's inbox on Monday morning* without him calling a code session. Working backwards from the artifact he actually reads.

---

## §1 The target output

This is the document Nathan opens on Monday morning. Everything else in this file exists to produce it.

```markdown
# Matchmaker Weekly Review — week of 2026-05-12
*Generated 2026-05-19 06:00 UTC · prior review · 4-week trend*

## 1. Health snapshot
| Metric                  | This week | Last week | 4w avg | Target  | Status |
|-------------------------|-----------|-----------|--------|---------|--------|
| Matchmaker runs         | 1,247     | 1,108     | 1,062  | growth  | ↑      |
| Step error rate         | 4.2%      | 2.1%      | 2.4%   | <2%     | ⚠ over |
| Abstain rate            | 18%       | 16%       | 17%    | 15-25%  | ✓      |
| Gold-signal rate (B+C)  | 6.3%      | 5.7%      | 5.4%   | grow    | ↑      |
| Rubric evals run        | 312       | 280       | 271    | n/a     | —      |
| Fabrications flagged    | 3 (0.96%) | 1 (0.36%) | 0.4%   | <0.5%   | ⚠ over |
| `would_demote_version`  | 1         | 0         | 0.3    | 0       | ⚠      |

## 2. What's failing — Q1
[bar chart: step × error_code, count]
- **explanation/LLM_TIMEOUT** spiked 3× on Tuesday 2026-05-14 (Anthropic status corroborated)
- **top_n/EMPTY_RESULT_SET** up 12% week-over-week — filter pipeline review recommended
- All other step×error_code pairs steady or down

## 3. Fabrication watch — rubric flags
- **3 fabrications** in 312 evaluations (vs 1/280 last week)
- All 3 used `prompt_version=matchmaker/explanation@v2`
- Sample fabrication evidence (rubric quotes):
  - `"likely supports digital literacy initiatives"` — no citation in provenance
  - `"founded by [name] in 1987"` — fabricated founder + year
  - `"funded similar organizations in your region"` — no geographic citation
- **Recommendation:** investigate v2 hallucination pattern; draft v3 candidate prompt; do not promote v2 further until rubric returns to baseline.

## 4. Signal gaps — gold-signal unresolved
| Path | Resolved | Unresolved | Reason |
|------|----------|------------|--------|
| Path A (Kit click) | 0 | 0 | path not yet live |
| Path B (export)    | 78  | 0  | clean |
| Path C (self-report) | 41 | 47 | 47 × `NO_RECENT_RUN` — known retention floor |

## 5. Patterns sitting in the data
### Q2 — Profile fields × apply rate
[bar chart: skipped-field × apply_rate]
- Users who skip **`year_founded`** apply to 40% fewer matches → surface this field more prominently in profile builder
- Users who skip **`focus_areas_secondary`** apply 8% MORE → secondary field may be producing noise; investigate

### Q3 — Mechanically matched, practically wrong
[table: top-20 foundations by presentations, sorted by apply rate ascending]
- "Acme Family Foundation": 47 presents, 0 applies — grant range may be mismatched
- "Beta Trust": 38 presents, 1 apply — investigate
- (… 18 more …)

### Q5 — Position bias
[bar chart: match_position × CTR]
- Position 1: 41% CTR · Position 6: 4% · Position 10: 1.2%
- **Strong rank dominance** — explanation quality unlikely to be moving the needle past position 3 in current presentation format

### Q6 — Cache hit rate trend
[line chart: daily feature_vector cache hit rate]
- Stable at 84%; no profile-churn spike

### Q7 — Funnel attrition
[funnel chart: 7 step retention from profile_intake → presentation]
- Steady 98% step-to-step except presentation → follow_up: 31%
- 69% of users do not act on any presented match within session

### Q8 — Manual workarounds
[bar chart: next_action_within_session after dismiss]
- 22% `search_manually` → users routing around the matchmaker after dismiss
- 18% `refine_profile`
- 60% `leave_session`

## 6. Promotion candidates (this week)
| Surface | Recommendation | Driver |
|---------|----------------|--------|
| explanation prompt | Draft `explanation@v3`; investigate v2 fabrication pattern | §3 fabrication watch |
| profile builder UI | Surface `year_founded` requirement more prominently | §5 Q2 |
| profile builder UI | Investigate or remove `focus_areas_secondary` field | §5 Q2 |
| top_n filter pipeline | Review filter_counts; possibly relax `score_threshold` | §2 + §5 Q3 |
| presentation layer | Test reduced-N presentation (5 instead of 10); position bias suggests low-rank matches are wasted | §5 Q5 |

## 7. Operations
- 3 P2 alerts fired this week (LLM_TIMEOUT spike Tuesday); all auto-recovered within retry window
- `data/gold_signal_pending.jsonl` length: 0 (clean)
- `data/gold_signal_unresolved.jsonl` growth: +47 (matches §4)
- Prompt promotion log: 0 promotions this week
- Salt rotation: not due (90 days since last)

## 8. Decisions to log this week
- [ ] Promote/draft `explanation@v3` based on §3
- [ ] Profile builder change based on §5 Q2
- [ ] Decide on filter pipeline tweak based on §5 Q3
- [ ] A/B test reduced-N presentation
```

That is the artifact. Now: the tools that produce it.

---

## §2 Working backwards — section-by-section

For each section above, what is the cell, what does it read, what helper functions does it need, and what does it emit.

### 2.1 Section 1 — Health snapshot

- **Cell:** `compute_health_snapshot(window_start, window_end, prior_windows)`
- **Reads:** `pipeline_history.jsonl` (range-filtered by `ts`).
- **Helpers needed:**
  - `load_telemetry(window_start, window_end, agent='matchmaker') → pd.DataFrame` — the universal loader.
  - `summarise_runs(df) → dict` — counts runs by `run_id`.
  - `summarise_step_errors(df) → dict` — outcome ≠ "ok".
  - `summarise_abstain(df) → dict` — explanation step, abstained count.
  - `summarise_gold(df) → dict` — follow_up step, applied_to_external_signal not null.
  - `summarise_rubric(df) → dict` — rubric rows: fabrication_flag, would_demote_version counts.
  - `compare_to_prior(this_week, prior_weeks) → dict` — deltas + 4-week mean.
- **Emits:** the table at §1. JSON + markdown.

### 2.2 Section 2 — Q1 step failure rates

- **Cell:** `query_q1(df) → pd.DataFrame` — exactly the Q1 SQL from matchmaker-instrumentation §6 ported to pandas/DuckDB.
- **Reads:** the same dataframe.
- **Helpers needed:**
  - `q1_step_errors(df) → pd.DataFrame`
  - `render_bar_chart(df, x, y, group_by, output_path)`
  - `narrate_q1(df, prior_df) → str` — turns the dataframe into the 1-2 sentences in §2 ("explanation/LLM_TIMEOUT spiked 3×…"). Rules-based first, LLM-narrated only if rules can't summarise.
- **Emits:** chart PNG + narration paragraph.

### 2.3 Section 3 — Fabrication watch

- **Cell:** `query_fabrications(df) → pd.DataFrame`
- **Reads:** rubric rows from `pipeline_history.jsonl` where `fabrication_flag == true`.
- **Helpers needed:**
  - `q_fabrications(df) → pd.DataFrame`
  - `group_by_prompt_version(df) → pd.DataFrame`
  - `extract_fabrication_evidence(df, sample_n=3) → list[str]` — pulls the rubric's `fabrication_evidence` field.
  - `recommend_fabrication_response(grouped_df) → str` — rules-based recommender. Example: "if all fabrications share a single prompt_version, recommend rollback or v{n+1} draft."
- **Emits:** evidence quotes + recommendation paragraph.

### 2.4 Section 4 — Signal gaps

- **Cell:** `query_unresolved(window_start, window_end) → pd.DataFrame`
- **Reads:** `data/gold_signal_unresolved.jsonl`, `data/gold_signal_pending.jsonl`.
- **Helpers needed:**
  - `load_unresolved(window_start, window_end) → pd.DataFrame`
  - `group_by_path_and_reason(df) → pd.DataFrame`
- **Emits:** the table at §4.

### 2.5 Section 5 — Patterns (Q2, Q3, Q5, Q6, Q7, Q8)

- **Cell:** one helper per query — `query_q2(df)`, `query_q3(df)`, `query_q5(df)`, `query_q6(df)`, `query_q7(df)`, `query_q8(df)`. Direct ports of matchmaker-instrumentation §6 sketches.
- **Helpers needed:**
  - `render_bar_chart`, `render_line_chart`, `render_funnel_chart` — three shared chart functions.
  - `narrate_pattern(df, query_name) → str` — rules-first narrator. Most queries can be summarised by simple thresholds ("X% greater than Y"); LLM narration only as fallback.
- **Emits:** six charts + six narration paragraphs.

### 2.6 Section 6 — Promotion candidates

- **Cell:** `synthesise_promotions(all_query_results) → pd.DataFrame`
- **Reads:** the outputs of §2-§5.
- **Helpers needed:**
  - `promotion_rules` — a small ruleset that maps observations to recommendations. Example: "if fabrication_flag count ≥ 3 in a week and all share a prompt_version, recommend a new prompt version." Rules live in YAML so they are version-controlled and reviewable.
- **Emits:** the §6 table. Each row carries a citation back to the section that produced it.

### 2.7 Section 7 — Operations

- **Cell:** `compute_ops_summary(window_start, window_end) → dict`
- **Reads:** PagerDuty / on-call equivalent (not yet built — for v1, hard-code "0 alerts" until the alerting layer exists); `data/promotions.jsonl`; `data/salt_rotations.jsonl`.
- **Helpers needed:**
  - `load_promotions(window) → pd.DataFrame`
  - `next_salt_rotation_due() → date`
- **Emits:** the bullet list at §7.

### 2.8 Section 8 — Decisions to log

- **Cell:** `extract_decisions(all_query_results, promotion_candidates) → list[dict]`
- **Reads:** all prior cells.
- **Helpers needed:**
  - `decision_template` — checklist items derived 1:1 from §6 promotion candidates.
- **Emits:** the §8 checklist. When Nathan ticks items off, the decision flows to `data/decisions.jsonl` (closing the promotion loop).

---

## §3 Tools needed (consolidated)

Everything above resolves to this list:

### 3.1 Data layer
- **`load_telemetry(window, agent, sphere?)`** — single entry point. Reads JSONL from a configured source (filesystem, S3, or HTTP). Returns a typed pandas DataFrame (or polars; same shape).
- **`load_unresolved(window)`**, **`load_promotions(window)`**, **`load_decisions(window)`** — sibling loaders.
- **Schema validation on load** — every row validates against the `MatchmakerEvent` Pydantic model before it enters the dataframe. Malformed rows go to `data/quarantine.jsonl` and surface in §7 ops summary.

### 3.2 Query layer
- **One function per Q1-Q8.** Pure pandas/polars/DuckDB; no LLM calls. These are the deterministic substrate.
- **A standing `queries.yaml`** that names each query and binds it to its function. Adding a query in future is a YAML entry plus a function, not a notebook edit.

### 3.3 Narration layer
- **Rules-first narrators** — small Python functions that turn dataframes into 1-2 sentence summaries. ~80% of narration should be rules-based and deterministic.
- **LLM-narration fallback** — for sections where rules can't capture the pattern (rare). Uses the same prompt-registry convention as the matchmaker (`documentation/prompts/review/narrate@v1.md` etc.).

### 3.4 Chart layer
- **Three shared chart functions** — bar, line, funnel. Rendered as PNG (for email) and SVG (for HTML). Plotly + kaleido is the likely stack.

### 3.5 Promotion-recommendation layer
- **`promotion_rules.yaml`** — versioned ruleset mapping observations to recommendations. Same versioning discipline as the prompt registry.
- **`synthesise_promotions(query_results) → DataFrame`** — applies the rules.

### 3.6 Rendering layer
- **Quarto** (Python + markdown + executable code blocks) renders to HTML and PDF. Likely better than Jupyter for this use case — the output is a publishable report, not an exploratory notebook.
- Alternative: Jupyter + nbconvert. Quarto is cleaner for the publishable-output use case.

### 3.7 Delivery layer
- **HTML report → static-site hosting.** Reports live at `reports.granthelperpro.internal/weekly/YYYY-MM-DD/index.html` (or wherever Nathan keeps internal artifacts). Each week's report is permalinked.
- **Markdown summary → Nathan's Obsidian.** A copy of the report's §1, §3, §6, §8 lands in `Obsidian/GTD/Projects/The Almoner Business/Weekly Reviews/YYYY-MM-DD.md` so it integrates with the existing review workflow.
- **Email digest → Nathan's inbox.** A short summary email with §1 health snapshot + §3 fabrication watch + §6 promotion candidates + a link to the full HTML. ConvertKit/Kit or plain SMTP.
- **Anomaly alert → Todoist or PagerDuty.** If any §1 metric breaches a hard threshold (fabrication rate >1%, step error rate >5%, `would_demote_version` >2 in a week), fire a Todoist task with priority 1.

### 3.8 Scheduler
- **GitHub Actions cron** — `on: schedule: cron: '0 6 * * 1'` (every Monday 06:00 UTC). Checks out the notebook repo, installs deps, runs `quarto render`, publishes to static-site host, mails the digest, fires anomaly alerts.
- **Backup: local cron** — a script that runs the same workflow on Nathan's home box if the cloud scheduler fails. Lower priority for v1.
- **Manual `make weekly-review` target** — so the report can be regenerated on demand without waiting for cron.

### 3.9 Storage
- **Telemetry source:** for v1, `pipeline_history.jsonl` lives in aigranthelper's filesystem and is rsynced or S3-synced nightly to wherever the notebook runs.
- **Reports archive:** static-site bucket, organised by date. 1-year retention default.
- **Decision log:** `data/decisions.jsonl` — Nathan's checkbox completions write here, closing the loop on §6 promotion candidates.

---

## §4 Does this need a separate project?

**Recommendation: yes — a dedicated observability sidecar.** Here is the reasoning and the proposed shape.

### 4.1 Why not aigranthelper

- aigranthelper is the Django SaaS that paying users hit. Mixing analytics tooling with production code creates:
  - Dependency bloat (pandas, plotly, Quarto, Jupyter — none of which production needs)
  - Deploy-cadence coupling (analytics changes should not require redeploying the user-facing app)
  - Different test ergonomics (notebooks vs Django views)
- The telemetry is *emitted* from aigranthelper, but the analysis runs *outside* it. Same pattern as observability stacks in general.

### 4.2 Why not OverSteward

- OverSteward is governance + dispatch for the *development* estate — what Sphere II calls "internal/DevOps" in the dispatch-playbook sense. It is about how Claude Code agents work the repos.
- The weekly review is observability for the *product* estate — Sphere I + III + IV in DETERMINISTIC_AGENTS terms. Different tenant, different audience, different cadence.
- Putting them in the same repo would force OverSteward's `registry.yaml` to grow a `product_analytics` section that has nothing to do with managing CLAUDE.md or souls. The conceptual mismatch is real.

### 4.3 Why a separate project

- Clean boundaries between *what the product does* and *how the product is observed*.
- Different deployment cadence (analytics runs on a schedule; product runs on user request).
- Different audience (Nathan + future Analyst persona; not paying users).
- Different dependencies (heavy data/notebook/charting libs).
- The four-sphere model implies multiple subjects of analysis over time (chatbot review, docs personalisation review, devops review). The analytics tool should outlive any single sphere subject.
- Honest answer to "where does this live in the layer map": it is its own outer layer for an analytics middle, with inner connectors to the telemetry sources. That structure deserves a repo.

### 4.4 Proposed shape

```
the-counting-room/                          # repo name — see §4.5
├── README.md
├── CLAUDE.md                               # @file imports oversteward shared/
├── pyproject.toml                          # python deps: pandas, polars, duckdb,
│                                           #   pydantic, quarto, plotly, kaleido
├── _quarto.yml                             # Quarto site config
├── notebooks/
│   ├── weekly-review.qmd                   # the main review (the §1 target)
│   ├── monthly-trend.qmd                   # 4-week retrospective (future)
│   └── ad-hoc/                             # one-shot questions Nathan throws at the data
├── src/the_counting_room/
│   ├── loaders.py                          # §3.1 data layer
│   ├── queries/
│   │   ├── matchmaker_q1_step_errors.py
│   │   ├── matchmaker_q2_field_skip.py
│   │   ├── … (Q3-Q8)
│   │   └── _registry.py                    # binds queries.yaml to functions
│   ├── narrators.py                        # §3.3 rules-first narrators
│   ├── charts.py                           # §3.4
│   ├── recommenders.py                     # §3.5 — applies promotion_rules.yaml
│   ├── delivery/
│   │   ├── obsidian.py                     # writes to Nathan's vault
│   │   ├── email.py                        # SMTP/Kit digest
│   │   ├── todoist.py                      # anomaly alerts (skill already shared)
│   │   └── publish.py                      # static-site upload
│   └── schemas.py                          # Pydantic models, mirrors matchmaker
│                                           #   schema from oversteward design docs
├── config/
│   ├── queries.yaml                        # query registry
│   ├── promotion_rules.yaml                # recommender ruleset
│   ├── thresholds.yaml                     # anomaly thresholds (fabrication >1%, etc.)
│   └── delivery.yaml                       # where to publish, who to email
├── prompts/                                # if any LLM narrators land — same registry
│   │                                         conventions as oversteward
│   └── review/
│       └── narrate-anomaly@v1.md
├── tests/
│   ├── test_loaders.py                     # schema validation
│   ├── test_queries.py                     # canonical fixtures → expected outputs
│   ├── test_recommenders.py                # ruleset behaviour
│   └── fixtures/
│       └── pipeline_history.sample.jsonl
├── .github/workflows/
│   ├── weekly-review.yml                   # cron: '0 6 * * 1' — runs the review
│   └── ci.yml                              # lint + tests on PR
└── Makefile                                # `make weekly-review`, `make test`, `make lint`
```

### 4.5 Name

A few candidates, each tied to a frame:

1. **`the-counting-room`** — Wodehouse-flavoured (bank counting rooms; the place where the day's numbers are reconciled). Matches Chestertron's voice. **Recommended.**
2. **`firmware-review`** — direct tie to the chip/firmware/appliance metaphor. Functional but clinical.
3. **`flywheel`** — references the compounding moat. Punchy but does not say what it *is*.

If the analytics sphere grows to cover chatbot and docs reviews in time, all three names still fit. `the-counting-room` is most distinct as a repo identifier in `gh repo list` and has the right "place where the numbers happen" flavour.

### 4.6 What stays in oversteward

- **The design docs** (DETERMINISTIC_AGENTS.md, matchmaker-instrumentation.md, gold-signal-ingestion.md, this file). These describe the *contract* the counting-room implements. The counting-room implements; oversteward designs. When a contract changes, oversteward owns the change.
- **The prompts directory** for matchmaker (the matchmaker reads them from aigranthelper at runtime per the registry's §9 implementation-home rule).
- **The architecture.md row** for the new repo. Add it to §1 with a `Pickup target: no (observability)` flag.

### 4.7 Cross-repo touchpoints

| Source | Consumer | What flows |
|---|---|---|
| aigranthelper | the-counting-room | `pipeline_history.jsonl` via nightly S3 sync (or HTTP pull) |
| oversteward | the-counting-room | `MatchmakerEvent` schema (vendored as a tiny package or copy-pasted from the design docs at v1) |
| the-counting-room | Nathan's Obsidian | Markdown summary per week |
| the-counting-room | Nathan's email | Digest + alert |
| the-counting-room | Todoist | Anomaly tasks |

The schema duplication is acceptable at v1 — a tiny vendored copy is cheaper than setting up a shared package. When the matchmaker's events stabilise (~3-6 months in), publish a `ghp-schemas` PyPI-style package that both sides depend on. Until then, the design doc is the source of truth.

### 4.8 Setup cost estimate

Rough budget for the v1 counting-room, sequenced:

1. **Repo + scaffolding** (1-2 hours): repo init, pyproject, CI skeleton, Quarto install.
2. **Loaders + schema** (2-3 hours): `load_telemetry`, Pydantic model, fixtures.
3. **One query + one chart end-to-end** (2-3 hours): Q1 only. Proves the stack works.
4. **Rest of queries** (Q2-Q8) (4-6 hours): each is a small pandas/SQL function plus a chart.
5. **Narrators + recommenders** (2-3 hours): rules-first; LLM fallback deferred.
6. **Delivery layer** (3-4 hours): Obsidian writer, email sender, Todoist alert.
7. **GH Actions cron + first live run** (2 hours): wire up, run end-to-end against fixture data, then against real data once a week's telemetry has accumulated.

Total ballpark: 16-23 hours of focused work. Honest range; could go longer if the telemetry source ingestion (rsync vs S3 vs HTTP) takes more than expected to plumb.

**Gating constraint:** the counting-room can be built ahead of any real telemetry by running against synthetic fixtures from §5 of matchmaker-instrumentation. It does not block on the matchmaker itself shipping. That means a meaningful v0 can land *before* the matchmaker, which is the right sequencing — the analysis layer is ready the day the first real event lands.

---

## §5 What does NOT belong in the counting-room

Drawing the boundaries explicitly so the project stays focused.

- **No request-path code.** Anything in the matchmaker's request path stays in aigranthelper. The counting-room is read-only against telemetry.
- **No prompt authoring.** Matchmaker prompts live in oversteward (design) and aigranthelper (implementation). The counting-room *evaluates* prompt outputs via the rubric; it does not author or modify the prompts themselves.
- **No user-facing surface.** The counting-room reports to Nathan, full stop. If a customer-facing analytics surface ever exists (a "your matchmaker performance" page), it lives in aigranthelper and reads from a curated subset of telemetry, not from this repo.
- **No governance.** Sync, dispatch, registry, souls — that is oversteward. The counting-room is a peer, not a tenant.

---

## §6 Open design questions (for Nathan)

These are decisions I cannot make alone — flagging them so the v1 build does not stall on a blocker.

1. **Telemetry transport.** Three viable options for moving `pipeline_history.jsonl` from aigranthelper to the counting-room: (a) S3 nightly sync, (b) HTTP pull endpoint on aigranthelper, (c) shared Postgres/DuckDB instance both write to and read from. **Recommendation:** option (b) — cheapest, fewest moving parts, lets the counting-room run anywhere with HTTP access. Trade-off: aigranthelper's `/internal/telemetry?since=...` endpoint must be authenticated (signed JWT from the counting-room's deploy environment).
2. **Hosting for the GH Actions runner.** GitHub-hosted runners cost compute minutes; self-hosted runners require infrastructure. For a weekly job that takes ~5-15 minutes, GitHub-hosted is fine; flag if private-repo CI minutes are tight.
3. **Quarto vs Jupyter+nbconvert.** Quarto is cleaner for publishable output; Jupyter is more familiar. **Recommendation:** Quarto, with a fallback `make weekly-review-jupyter` target for ad-hoc exploration.
4. **Obsidian write path.** The counting-room runs in CI but writes to Nathan's Obsidian vault, which lives on his box. Three options: (a) commit to the Obsidian git repo (if it is git-backed — Home_Obsidian is), (b) send the markdown as an email attachment for Nathan to file manually, (c) skip Obsidian and rely on email + HTML. **Recommendation:** (a) for Home_Obsidian since it is git-backed.
5. **Anomaly alerting destination.** Todoist (already integrated, lightweight) vs PagerDuty (formal on-call) vs email (no separate inbox). **Recommendation:** Todoist for v1; revisit if weekly-review anomalies become high-frequency.

---

## §7 Maintenance

- Update §1 when the target report changes (a new section, a removed section, a renamed metric).
- Update §3 when a new tool joins the stack (new chart type, new delivery channel).
- Update §4.4 layout when the counting-room repo grows or restructures.
- §6 open questions should be resolved before the counting-room ships v0; remove each question as it is answered, with the resolution captured in §4.

*Last updated: 2026-05-13 (v0 — companion to matchmaker-instrumentation.md and gold-signal-ingestion.md).*
