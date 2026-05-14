---
session_date: 2026-05-13
status: complete — Fiscus repo created end-to-end, GH remote live, conda env green, 25/25 tests, 3 andon-channel issues filed
context: Conversation spanned 2026-05-07 → 2026-05-14 through context compaction. Started as a "survey this repo" ask for ROADMAP + deterministic-agents docs; evolved into a strategic-frame conversation that produced 5 design captures in oversteward, then the Fiscus scaffold + GH remote + green local suite, then 3 self-observational andon issues.
---

## Where we left off

Long strategic + scaffolding session. Two repos touched, six conceptual phases:

1. **Survey + initial docs (2026-05-07).** Read the oversteward state and drafted `documentation/ROADMAP.md` + `documentation/DETERMINISTIC_AGENTS.md`. First DETERMINISTIC_AGENTS draft was estate-wide and framed customer-facing as the LAST sphere to build.
2. **Strategic refocus (2026-05-07).** Nathan pasted his chat with Chestertron on workflow-as-IP / four spheres / design-first-plus-capture-first synthesis. **Inverted the framing** — Grant Helper Pro Matchmaker is the design lead (Sphere I), not the deferred sphere. Rewrote DETERMINISTIC_AGENTS.md to match (chip / firmware / appliance frame, GHP-anchored four spheres, five-move synthesis).
3. **Three concrete artifacts (2026-05-08).** `documentation/captures/matchmaker-instrumentation.md` (full per-step telemetry schema, 8 standing analysis queries Q1-Q8, redaction rules); `documentation/prompts/README.md` + `prompts/matchmaker/explanation@v1.md` + `prompts/matchmaker/quality-rubric@v1.md` (prompt registry conventions + the matchmaker generation prompt and LLM-as-judge rubric); `documentation/captures/gold-signal-ingestion.md` (three concrete ingestion paths for `applied_to_external_signal` — Kit email click, in-app export, manual self-report, with the `run_id: null` exception for self-report).
4. **Weekly-review notebook sketch (2026-05-13).** `documentation/captures/weekly-review-notebook.md` — target Monday-morning report worked backwards to the tool stack. Originally recommended a separate sidecar repo called "the-counting-room"; Nathan named it **Fiscus** instead (Latin: imperial treasury — "our learning is our treasure").
5. **Kaizen critique (2026-05-13).** Nathan asked for an honest best-practices comparison. `documentation/captures/kaizen-architecture.md` — five foundational gaps, eight material gaps, six notable gaps in the original sketch. Surfaced the missing **Standardize step** as the biggest miss; sphere-siloed thinking as second. Proposed three-level registry (subjects.yaml + per-subject contracts + cross-cutting shared/). Five open questions filed at §9.
6. **Fiscus genesis (2026-05-14).** Nathan resolved all five §9 open questions + three additional directives (Fiscus observes Fiscus; local testing including gaudi + boy scout from day one; Fiscus's own meta-loop is foundational). Scaffolded the whole Fiscus repo, created the GH remote, created the conda env, ran the test suite green.

Current state of both repos clean as of session close.

## Fiscus — new repo created end-to-end

**Repo:** [github.com/NathanKrupa/Fiscus](https://github.com/NathanKrupa/Fiscus) — private. Local path: `C:\Users\natha\OneDrive\Tech\Python\Fiscus`. Branch: `main`. Two commits.

**Genesis commit (`fd6a4c4`)** — 48 files, 3,290 lines:
- `subjects.yaml` — six subjects registered: ghp-matchmaker (stub), ghp-general (stub, cross-cutting AG telemetry beyond matchmaker), dispatch (stub), grantspider-crawler (stub), research-drift (stub), fiscus-meta (stub, quarterly — Fiscus observes Fiscus).
- `shared/lessons.jsonl` — 10 lessons backfilled from oversteward `feedback_*` memory.
- `shared/invariants.yaml` — 15 invariants in three scopes: I-X-* (cross-cutting from oversteward architecture.md §3), I-F-* (Fiscus itself), I-MM-* (matchmaker), I-D-* (dispatch).
- `shared/decisions/2026-05-14-0001-fiscus-genesis.md` — full ADR documenting the multi-subject decision + alternatives + standardize checklist.
- `shared/decisions/_template.md`, `shared/postmortems/_template.md` (with 5-whys structure), `shared/experiments/_template.yaml`.
- `pyproject.toml` (Python 3.14, ruff strict + ANN, pyright strict, pytest + cov + timeout, gaudi in dev deps).
- `.pre-commit-config.yaml` (ruff + format + gaudi error-class).
- `.github/workflows/ci.yml` — six jobs: lint, typecheck, test, gaudi, **boy-scout-check** (per-file gaudi count ≤ main on touched files, invariant I-F-4), **promotion-lesson-check** (touching prompts/ subjects/ or shared/decisions/ requires a `lessons.jsonl` row added, invariant I-F-1).
- `.github/workflows/weekly-review.yml` — Monday 06:00 UTC cron skeleton (delivery wired in later phases).
- `.github/ISSUE_TEMPLATE/andon.md` (canonical) + `promotion.md` + `PULL_REQUEST_TEMPLATE.md`.
- `scripts/boy_scout_check.py` + `scripts/promotion_lesson_check.py` (Phase 0 stubs; full implementations Phase 1).
- `src/fiscus/` — `schemas.py` (Pydantic models per subject + envelope + LessonRow + AndonRow), `registry.py` (subjects.yaml loader + by-project/by-agent/by-sphere derived views), `cli.py` (Click entry point), `loaders.py` (skeleton), `andon.py` (GH-aggregation skeleton), `queries/__init__.py`, `delivery/__init__.py`.
- `tests/` — 25 tests: `test_registry.py` (10), `test_schemas.py` (6), `test_invariants.py` (5), `test_lessons.py` (4).
- `documentation/ARCHITECTURE.md`, `FISCUS.md`, `README.md`, `CLAUDE.md`.

**Green-suite commit (`25236d3`)** — first end-to-end run on the Fiscus env surfaced:
- 1 real test bug (DispatchEvent test missing required `agent` field; fixed).
- pytest 9 + pytest-cov 7 plugin-loading issue; moved `--cov` args from default `addopts` to a separate `make cov` target.
- 13 manual ruff fixes (long ABOUTME headers split per CLAUDE.md two-line pattern, long click.echo / print wrapped, `pytest.raises(Exception)` narrowed to `pytest.raises(ValidationError)`, etc.).
- Final state: `pytest` 25/25 green, `ruff check .` All checks passed, `ruff format --check .` 16/16 already formatted.

## Oversteward changes this session (in this PR)

- `documentation/ROADMAP.md` — new; consolidates what's done / what's in flight / what's next from MASTER_TODO, TODO_BACKLOG, architecture.md §5, IDEA_STORE. Strategic-frame note added on the workflow-as-IP thesis + Fiscus landed.
- `documentation/DETERMINISTIC_AGENTS.md` — new; GHP-anchored four-sphere blueprint (Matchmaker as design lead, parallel Internal/DevOps, deferred Service + Docs gated on Sphere I telemetry). §10 "Artifacts landed" indexes the five companion captures.
- `documentation/captures/matchmaker-instrumentation.md` — new; envelope + 8 step payloads + 4-tier redaction discipline + 8 standing analysis queries.
- `documentation/captures/gold-signal-ingestion.md` — new; three Path designs (Kit email / export / self-report) + the `run_id: null` exception for self-report.
- `documentation/captures/weekly-review-notebook.md` — new; Monday-morning target output → tool stack worked backwards (now superseded in §4 by kaizen-architecture.md scope).
- `documentation/captures/kaizen-architecture.md` — new; best-practice critique + redesign; §9 all five open questions marked RESOLVED with the chosen answers.
- `documentation/prompts/README.md` + `prompts/matchmaker/explanation@v1.md` + `prompts/matchmaker/quality-rubric@v1.md` — prompt registry conventions + the two matchmaker v1 prompts (design v0; implementation moves to aigranthelper per registry §9).
- `registry.yaml` — Fiscus entry added at end of context list.
- `architecture.md` §1 — Fiscus row added (`Pickup target: no (observability)`); §2 — three new cross-repo seams (AG→Fiscus telemetry pull, Oversteward→Fiscus dispatch read, all-pickup-repos→Fiscus andon aggregation).

## Issues filed this session

| Repo | # | Title |
|---|---|---|
| aigranthelper | [#514](https://github.com/NathanKrupa/aigranthelper/issues/514) | feat(matchmaker): add user feedback button on match outputs (Path C wiring) |
| aigranthelper | [#515](https://github.com/NathanKrupa/aigranthelper/issues/515) | feat(telemetry): general usage instrumentation + Fiscus pull endpoint (whole-product observability) |
| aigranthelper | [#516](https://github.com/NathanKrupa/aigranthelper/issues/516) | chore(observability): add andon issue template + label (Fiscus channel) |
| grantspider | [#827](https://github.com/NathanKrupa/grantspider/issues/827) | chore(observability): add andon issue template + label (Fiscus channel) |
| wphelper | [#169](https://github.com/NathanKrupa/wphelper/issues/169) | chore(observability): add andon issue template + label (Fiscus channel) |
| ai-assistants | [#81](https://github.com/NathanKrupa/ai-assistants/issues/81) | chore(observability): add andon issue template + label (Fiscus channel) |
| Oversteward | [#37](https://github.com/NathanKrupa/OverSteward/issues/37) | chore(observability): add andon issue template + label (Fiscus channel) |
| Fiscus | [#1](https://github.com/NathanKrupa/Fiscus/issues/1) | [andon] Makefile $(PYTEST) resolves to base-env pytest, not Fiscus-env pytest |
| Fiscus | [#2](https://github.com/NathanKrupa/Fiscus/issues/2) | [andon] conda run -n Fiscus emits "Did not find path entry" warning on every invocation |
| Fiscus | [#3](https://github.com/NathanKrupa/Fiscus/issues/3) | [andon] VSCode IDE diagnostics stale on edited files |

## Operational changes

- **Fiscus conda env created** — Python 3.14.4, full dev extras installed.
- **`andon` label created** on Fiscus + aigranthelper (Fiscus self + the test from earlier). Other four pickup repos have it pending per the distribution issues.
- **FI shorthand added to memory** alongside AG / GS / WP — Fiscus issues reference as "FI N".

## Memory writes this session

- `feedback_repo_shorthand.md` updated — added "FI = Fiscus" alongside the existing AG / GS / WP triplet.

## Gotchas / context for next session

1. **Fiscus#1 is real and high-severity** — `make test` is documented as the non-negotiable local entry point in Fiscus CLAUDE.md, but `$(PYTEST) = conda run -n Fiscus pytest` resolves to the *base* env's pytest. Working form is `conda run -n Fiscus python -m pytest`. Two-line Makefile fix sketched in the issue. Fix before anyone tries to follow the CLAUDE.md instructions.
2. **The genesis commit landed direct to Fiscus `main`** — Fiscus has no branch protection yet (repo just born); subsequent work flows through PRs. Add branch protection on Fiscus `main` as a follow-up (matches oversteward + gaudi pattern).
3. **Two AG issues (#514, #515) are the producer-side prerequisites for any real telemetry into Fiscus.** Until those ship, Fiscus runs against fixture data. Phase 1 of Fiscus can start regardless — fixtures are the design-target.
4. **Five andon-template-distribution issues are tracking-only** — Nathan held them at issue-only per directive 2026-05-14; no auto-PR.
5. **Oversteward #33 (retire `/dispatch` skill) remains open from 2026-05-01.** Not from this session but tangentially related (this session's DETERMINISTIC_AGENTS.md and architecture.md treat in-session pickup as default, matching the disposition #33 codifies). Worth a look when convenient.
6. **The `gold_signal_unresolved.jsonl` / `gold_signal_pending.jsonl` files are designed but not yet created** in Fiscus or AG. They will appear when Phase B (export download ingestion) ships in AG, per gold-signal-ingestion.md §6 build order.
7. **`subjects/{id}/fixtures/` directories exist as empty placeholders in Fiscus** — Phase 1 work populates them. The matchmaker fixture set is sketched in matchmaker-instrumentation.md §5 + explanation@v1.md §5.
8. **Untracked in oversteward working tree** — `files.zip` and `references/` were present at session start and are NOT mine. Left alone. Should be cleaned up or git-ignored separately.
