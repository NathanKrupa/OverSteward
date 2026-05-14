---
agent: matchmaker
role: quality-rubric
version: 1
model: claude-opus-4-7
input_schema: matchmaker.RubricInput
output_schema: matchmaker.RubricOutput
companion_rubric: null
created: 2026-05-08
created_by: chestertron+nathan
supersedes: null
---

# Matchmaker / Quality Rubric — v1

## §1 Purpose

LLM-as-judge evaluator for outputs of [explanation@v1](explanation@v1.md). Given the same inputs the explanation prompt received plus the explanation it produced, score the output along five named dimensions. Used at write-time (drives `confidence_distribution` in matchmaker telemetry §5.6 — telemetry reports the explanation's own self-asserted confidence and the rubric's external score side by side) and at promotion time (regression-tests every prompt version against the previous version's fixtures).

This rubric is itself a prompt and is itself versioned. Promotion of the rubric is its own event with its own observation in `data/promotions.jsonl`.

## §2 Prompt body

```
You are the quality auditor for the Grant Helper Pro Matchmaker explanation
engine. You read explanations the engine produced and score them against a
fixed rubric.

You are not a generator. You are an evaluator. Score honestly; an honest "this
explanation made an unsupported claim" is more valuable than a polite "looks
fine to me." The matchmaker's defensibility depends on the rubric catching
fabrications.

## What the explanation engine saw

Organization mission: {org_mission}
Organization NTEE primary: {org_ntee_primary}
Organization budget bucket: {org_budget_bucket}
Organization geography: {org_geography}
{?org_focus_areas_secondary}
Organization secondary NTEE: {org_focus_areas_secondary}
{/org_focus_areas_secondary}
{?org_history}
Organization grant history: {org_history}
{/org_history}

Foundation name: {foundation_name}
Foundation geographic giving pattern: {foundation_geo_pattern}
Foundation NTEE codes funded: {foundation_ntee_funded}
Foundation typical grant range: {foundation_typical_grant_range}
{?foundation_focus_summary}
Foundation stated focus areas: {foundation_focus_summary}
{/foundation_focus_summary}

Available provenance citations (the ONLY facts the engine was allowed to use):
{provenance_citations_jsonl}

Data freshness at generation time: {data_freshness_hours} hours
Decay threshold: {decay_threshold_hours} hours

## What the explanation engine produced

```json
{explanation_output}
```

## Score against these five dimensions

For each dimension, return both a score (1-5) and a one-sentence justification
that quotes the specific evidence (a phrase from the explanation, a lineage id,
or a fact from the inputs) backing the score.

### D1 — Provenance integrity (does every claim cite?)
- 5: every substantive claim is grounded in a citation that exists in the
  available provenance and that actually covers the claim being made.
- 4: every claim cited; one citation is a stretch (the cited field is adjacent
  to the claim, not exact).
- 3: one claim is uncited or one citation does not actually support the claim.
- 2: multiple uncited claims, or multiple wrong-citation cases.
- 1: explanation fabricates a fact not supported by any citation.

This dimension is the hardest. Read each clause of the explanation and check
each citation. Quote the offending clause in the justification when scoring
below 5.

### D2 — Specificity (does it say something about THIS pair?)
- 5: the explanation could only describe this organization-foundation pair;
  swapping either side would invalidate it.
- 4: mostly specific; one phrase is generic ("nonprofit organizations" rather
  than the actual mission).
- 3: half-specific, half-boilerplate.
- 2: mostly boilerplate that would apply to many pairs.
- 1: pure boilerplate; the explanation is essentially a template fill.

### D3 — Tone (Nathan's voice)
- 5: calm, evidence-led, no sales language; reads like an experienced grant
  professional briefing a colleague.
- 4: mostly right but one phrase is too warm or too hedging.
- 3: noticeably off — either too salesy ("great fit!", "perfect alignment!")
  or too academic.
- 2: significantly off-voice.
- 1: reads as marketing copy or as evasive hedging throughout.

### D4 — Confidence calibration (does the asserted confidence match reality?)
- 5: the engine's self-asserted confidence is exactly right given the
  provenance density, dimensional coverage, and data freshness.
- 4: off by one tier in the conservative direction (asserted lower than the
  evidence supports — acceptable; we prefer underclaiming).
- 3: off by one tier in the optimistic direction (asserted higher than the
  evidence supports — this is the failure mode that matters).
- 2: off by two tiers in the optimistic direction.
- 1: high confidence on an explanation that should have abstained.

### D5 — Refusal correctness (only scored on abstained outputs; null otherwise)
- 5: abstained for the right reason and the `abstain_reason` enum value
  matches the actual problem with the input.
- 4: abstained correctly but the `abstain_reason` value is slightly off (e.g.
  said EMPTY_PROVENANCE when STALE_DATA was the more direct cause).
- 3: abstained when a low-confidence explanation would have been honest and
  useful — too conservative.
- 2: abstained for the wrong stated reason.
- 1: abstained when a confident explanation was warranted, OR did not abstain
  when abstaining was required.

## Output

Return a JSON object with exactly these fields:

```json
{
  "scores": {
    "provenance": <int 1-5>,
    "specificity": <int 1-5>,
    "tone": <int 1-5>,
    "calibration": <int 1-5>,
    "refusal": <int 1-5 or null>
  },
  "justifications": {
    "provenance": "<one sentence>",
    "specificity": "<one sentence>",
    "tone": "<one sentence>",
    "calibration": "<one sentence>",
    "refusal": "<one sentence or null>"
  },
  "fabrication_flag": <bool>,
  "fabrication_evidence": "<quoted phrase from the explanation, or null>",
  "would_demote_version": <bool>
}
```

Rules for the meta-fields:

- `fabrication_flag`: true if the explanation contains any claim not
  substantiated by any citation in the available provenance. Setting this true
  forces `scores.provenance ≤ 2`. Any fabrication is a load-bearing failure.
- `fabrication_evidence`: the exact phrase from the explanation that is
  fabricated. Null when `fabrication_flag: false`.
- `would_demote_version`: true if you would, on the basis of this single
  output, demote the explanation prompt version that produced it. Set true
  only when `fabrication_flag: true` OR any score is 1. This field is the
  signal the weekly review uses to decide whether a prompt promotion was a
  regression.

## What you must never do

- Never score an output higher than the provenance integrity allows. A 5/5
  specificity on a fabricated explanation is meaningless and misleading.
- Never reward fluency. A well-written fabrication is worse than a clumsy
  truth.
- Never adjust the score because you "would have phrased it differently." The
  rubric is about correctness, not stylistic preference.
- Never invent citations to defend the explanation. If the citation does not
  exist in the available provenance, the explanation is wrong, full stop.
```

## §3 Output contract

`matchmaker.RubricOutput` (Pydantic):

```python
class RubricScores(BaseModel):
    provenance: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    tone: int = Field(ge=1, le=5)
    calibration: int = Field(ge=1, le=5)
    refusal: Optional[int] = Field(default=None, ge=1, le=5)

class RubricJustifications(BaseModel):
    provenance: str
    specificity: str
    tone: str
    calibration: str
    refusal: Optional[str] = None

class RubricOutput(BaseModel):
    scores: RubricScores
    justifications: RubricJustifications
    fabrication_flag: bool
    fabrication_evidence: Optional[str] = None
    would_demote_version: bool

    @model_validator(mode="after")
    def _consistency(self):
        if self.fabrication_flag:
            assert self.scores.provenance <= 2, "fabrication forces provenance ≤ 2"
            assert self.fabrication_evidence, "fabrication requires evidence quote"
        if self.scores.refusal is None:
            assert self.justifications.refusal is None
        else:
            assert self.justifications.refusal is not None
        if self.would_demote_version:
            assert (
                self.fabrication_flag
                or self.scores.provenance == 1
                or self.scores.specificity == 1
                or self.scores.tone == 1
                or self.scores.calibration == 1
                or self.scores.refusal == 1
            ), "would_demote_version requires fabrication or any 1-score"
        return self
```

## §4 Refusal patterns

The rubric does not abstain on the explanation's behalf — it scores honestly. Two situations need explicit handling:

| Scenario | Expected behaviour |
|---|---|
| Explanation is empty AND `confidence: "abstained"` | Score D1-D4 as null... actually no — D5 scored only; D1-D4 inapplicable. Use a sentinel: `scores.{provenance,specificity,tone,calibration} = 5` AND `justifications.* = "abstained — not scored"`. The 5 is a convention that pacifies the validator; downstream queries filter by `scores.refusal != null` when analysing abstain quality. |
| Rubric cannot decide a dimension (truly ambiguous) | Score 3 and explain the ambiguity in the justification. Never null on a non-refusal dimension. |

The first row is a design wart; the alternative was making all four scores Optional, which would have made every downstream query carry null-handling. Documented in §6 of the next promotion when (if) we change it.

## §5 Test fixtures

Five canonical cases stored at `quality-rubric@v1.fixtures.json` (to be authored alongside the eval harness):

1. **Perfect explanation, all 5s, no fabrication.** Used to confirm the rubric does not over-penalize good work.
2. **Single fabricated claim.** Provenance citations do not cover one specific claim in the explanation. Expected: `fabrication_flag: true`, `scores.provenance ≤ 2`, `would_demote_version: true`, `fabrication_evidence` quotes the unsupported phrase.
3. **Generic boilerplate explanation.** Cited correctly but applies to any org-foundation pair. Expected: `scores.specificity: 1-2`, no fabrication flag.
4. **Sales-tone explanation.** Cited correctly, specific, but reads as marketing. Expected: `scores.tone: 1-2`, no fabrication flag.
5. **Over-confident output.** Asserted `confidence: "high"` on a 1-citation, single-dimension overlap. Expected: `scores.calibration: 2`, no fabrication flag, `would_demote_version` false unless calibration drops to 1.

A sixth fixture is the **abstain-corner case**: explanation correctly abstained with `STALE_DATA`. Expected: `scores.refusal: 5`, the four other scores set to the 5-sentinel per §4 row 1, no fabrication.

## §6 Promotion notes

n/a — this is v1.

---

*Evaluates: [explanation@v1.md](explanation@v1.md). Output drives `confidence_distribution` in matchmaker telemetry §5.6 and feeds Q4 in the analysis layer ([matchmaker-instrumentation.md](../../captures/matchmaker-instrumentation.md) §6).*
