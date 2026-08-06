ABOUTME: Design for using documentation authoring as a user-experience triage instrument.
ABOUTME: Nathan's idea, 2026-08-06; the supporting evidence was produced accidentally the same day.

# Documentation as UX triage — "The Docent"

*Working name. A docent walks a visitor through the house and explains it. Where the
explanation fails, the fault is usually the house.*

---

## 0. Premise

**An agent that must write a true sentence about a product cannot write one about an
incoherent product.** The failure to explain is a defect signal, and it is available for
free as a by-product of documentation work we were doing anyway.

This is Nathan's idea (2026-08-06). What follows is the case for it, the case against
over-trusting it, and what it would take to build.

The uncomfortable strength of the proposal is that **the experiment already ran, by
accident, before anyone framed it as an experiment.**

---

## 1. The evidence

On 2026-08-06 the `docs-author` agent rewrote three help articles. It was given no
audit brief, no instruction to look for bugs, and no access to bug reports. Its only
relevant instruction was *never describe a control you have not verified exists*.

Four product defects fell out. **None had been found by code review, by CI, or by a user
report.**

| Finding | Filed | How the documentation attempt exposed it |
|---|---|---|
| Account deletion promises subscription cancellation, a 30-day purge, anonymisation, and rescind-by-sign-in. It performs **none** of the four. A customer who deletes keeps being charged and cannot sign in to stop it. | AG#1468 | The agent tried to describe what deletion does, read `request_account_deletion`, and could not reconcile two lines of code with four promises on the page. |
| The deadline-window filter silently drops every funder with **no known deadline**, not merely those outside the window. | AG#1464 | It tried to explain what the filter does and found the docstring said something the UI did not. |
| "With Grant History" is implemented as `asset_amount__gt=0` — reported assets, not grant history. | AG#1465 | It could not write an honest sentence describing the control, so it omitted the filter entirely rather than repeat a false label. |
| Leaving **Website** blank on onboarding screen one silently skips screen two *and* leaves a first-run checklist item permanently unticked. | unfiled | It traced the wizard's redirect logic to describe the flow accurately and found a branch no user is told about. |

Lesser findings from the same three runs: the sidebar says **Matches** while the page is
headed **Find Funders**; the published promo codes are stale and one was probably never
right; the foundation count in customer-facing prose understated the database by roughly
**67,000**; and the score-legend `<details>` element cannot be screenshotted without an
interaction step.

Four defects from three articles, at the cost of work already being done, is a better
yield than most deliberate audits.

---

## 2. What it detects — and what it does not

This distinction is the whole design. Getting it wrong turns a useful instrument into
false confidence.

**It detects incoherence.** Things that cannot be described truthfully: labels that lie,
promises the code does not keep, behaviour with undisclosed preconditions, two names for
one concept.

**It does not detect confusion.** An agent reading source has *more* information than a
user. It is never lost, never impatient, never gives up. It will read `_redirect_after_valid_post`
and understand the wizard perfectly — where a real person would simply be baffled and
close the tab.

So the instrument finds a **subset**: things that are unexplainable are almost always
also unusable, but plenty of unusable things are perfectly explainable. A tedious flow, a
button in the wrong place, a form that is merely too long — all invisible here.

**This must be stated wherever the output is consumed.** The failure mode is not a bad
finding; it is somebody reading a clean report and concluding the UX has been audited.
It has not. It has been checked for coherence.

It is a complement to watching a real person use the product, and a cheap one. It is not
a substitute, and the moment it is treated as one it becomes actively harmful.

---

## 3. The friction taxonomy

Each shape is a recognisable failure to write a true sentence. The taxonomy matters
because it makes the signal typed rather than anecdotal, and typed findings can be
counted, deduplicated, and tracked over time.

| Shape | The agent's experience | What it usually means |
|---|---|---|
| `unnameable-control` | Cannot say "click X" — no stable label, or the label contradicts the behaviour | The control lies, or nobody owns its name |
| `undisclosed-precondition` | Cannot explain without "but only if…" | A hidden branch the user is never told about |
| `copy-contradicts-code` | The page claims something the code does not do | A promise being made to customers on false pretences |
| `synonym-collision` | Two names for one concept, both live | Nobody owns the product vocabulary |
| `explanation-inflation` | Needs a paragraph where a sentence should do | The feature is too complex, or is really several features |
| `dead-end` | The honest instruction is "contact support" | A hole in the product with a human patching it |
| `unphotographable` | Cannot be screenshotted without an interaction step | Collapsed, buried, or modal — often a thing users never find |

`unphotographable` was not predicted; it emerged from a real run. Expect the taxonomy to
grow, and treat additions as findings in their own right.

---

## 4. Mechanism

Nothing new is needed to *produce* the signal. It is already produced and then thrown
away — buried in prose at the end of a run and lost when the run ends.

A run works like this today:

1. The agent is asked to document a surface.
2. It reads the code and the live pages to verify every claim.
3. Where it cannot verify, it cuts the claim and mentions it in a closing report.
4. The report is read once by a human and discarded.

Step 3 is the instrument. Step 4 is the waste.

### 4.1 Two modes

**Article mode** — the current behaviour. Friction is a by-product of shipping an
article. High precision (the agent cared enough to need the sentence), limited coverage
(only surfaces that warrant articles).

**Sweep mode** — the unlock. Point the agent at a surface with *no* article and ask it to
document it. **Whether the article ever ships is irrelevant.** The friction encountered on
the way is the audit. This makes coverage a scheduling decision rather than a content
decision, and it reaches surfaces nobody intends to write about — Programs, Team
settings, funder detail, the consultant portfolio.

Sweep mode is where this stops being a happy accident and becomes an instrument.

---

## 5. Output contract

Findings must be typed, not prose. Prose findings do not survive the run.

```yaml
ux_friction:
  - shape: copy-contradicts-code        # from the §3 taxonomy
    surface: /account/danger/           # route or admin path
    summary: >-
      The deletion page promises subscription cancellation, a 30-day purge,
      anonymisation and rescind-by-sign-in. request_account_deletion performs
      none of them.
    evidence:                           # file:line, required — no evidence, no finding
      - apps/accounts/services/organization.py:322
      - templates/account_billing/danger.html
    user_consequence: >-                # required: what a real person loses
      Deletes the account, keeps being charged, cannot sign in to stop it.
    severity: high                      # high | medium | low
    confidence: certain                 # certain | probable — hedged findings are allowed but marked
```

Two fields carry the weight:

- **`evidence` is mandatory.** A finding without a file:line is a hunch, and hunches are
  what make audit output unreadable.
- **`user_consequence` is mandatory.** It forces the agent to state the harm in terms of
  a person rather than a code smell. If it cannot, the finding is probably a preference.
  This field is also what makes the issue worth filing.

---

## 6. Where findings go

Estate convention already answers this: UI findings become GitHub issues with the
`design` label, never a separate tracking document. Extend it — `design` plus a
`ux-triage` label so the provenance is legible and the yield is measurable.

**Deduplication is the hard part**, and it is worth solving before the first sweep rather
than after. A weekly sweep over the same surfaces will rediscover the same friction every
time. Match on `(shape, surface, evidence)` against open *and closed* issues; a closed
finding that reappears is itself a finding — either it regressed, or it was closed
without being fixed.

Filing should be **proposed, not automatic**, for the first several runs. The failure
mode is issue spam, and the fastest way to kill the instrument is to make its output
something Nathan has to clean up.

---

## 7. Failure modes

Named plainly, because each one is a way this becomes worse than nothing.

| Failure | Why it happens | Mitigation |
|---|---|---|
| **False confidence** | A clean report reads as "the UX is fine" | §2 restated at the top of every report; the word "audit" avoided |
| **Issue spam** | Every run files everything it noticed | Mandatory `user_consequence`, severity floor, propose-don't-file until calibrated |
| **Hallucinated friction** | The agent claims a control is missing when it exists | Mandatory `evidence`; a finding with no file:line is dropped, not hedged |
| **Rediscovery churn** | Weekly sweeps re-file known friction | Dedup on `(shape, surface, evidence)` against open **and** closed issues |
| **Taxonomy capture** | Everything gets filed as the vaguest shape | Review the shape distribution; if one bucket dominates, the taxonomy is wrong |
| **Displacing real testing** | "We run UX triage" becomes a reason not to watch users | Say the limit out loud, in the report, every time |

### 7.1 How we would know it is not working

- Findings stop having a `user_consequence` anyone recognises
- Yield falls to near zero on surfaces nobody has documented yet — meaning it is only
  finding what a human would have found anyway
- Filed issues get closed as `wontfix` at a high rate — the severity bar is wrong
- The same finding reappears across sweeps without either being fixed or dedup catching it

---

## 8. Relationship to what already exists

- **`docs-author`** (OverSteward `shared/agents/docs-author.md`) already does the work and
  already writes the report. This design adds a typed section, a taxonomy, and a
  destination — not a new agent.
- **AG#1270 drift detection** reconciles docs against the live site after each Tuesday
  promotion. That is the natural cadence for sweep mode too: the surfaces that changed are
  exactly the surfaces worth re-documenting.
- **Fiscus** is the estate's observation-and-kaizen platform and owns the lessons corpus.
  Friction yield over time — shapes, surfaces, fix rates — is Fiscus-shaped data. Open
  question in §9.

---

## 9. Open decisions

1. **Name.** "The Docent" is a working title in the household register (Telegraph,
   Vintner, Almoner, Exchequer). Nathan's call.
2. **Does friction yield become a Fiscus subject?** It is genuine kaizen telemetry —
   which surfaces generate friction, which shapes dominate, whether fix rate keeps pace
   with discovery. Adds a contract and a pull path; defer if the yield is small.
3. **Sweep cadence.** Tied to the Tuesday promotion (only changed surfaces), or an
   independent rotation across all surfaces regardless of change?
4. **Auto-file or propose?** Recommended: propose for the first several runs, then
   revisit with real numbers.
5. **Does it stay AG-only?** The instrument is product-agnostic. GrantSpider has no
   customer-facing UI, but the estate's internal tools do.
6. **Severity floor for filing.** `low` findings may be worth counting but not filing.

---

## 10. What this is, in one paragraph

We already pay an agent to write true sentences about the product. Where it cannot, the
product is at fault, and today that discovery is thrown away at the end of a run. This
design keeps it: a typed finding, with evidence and a stated human consequence, filed
where UI findings already go. It is the cheapest usability instrument available to a
solo operator — and it finds incoherence, not confusion, which is a real subset and not
a substitute for watching somebody use the thing.
