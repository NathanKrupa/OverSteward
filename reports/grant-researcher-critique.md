# Grant Researcher Subagent — Critique, Lacunae, and Suggestions

**Date:** 2026-03-09
**For:** Nathan Quiring, workshop review
**From:** Chestertron analysis

---

## What This Agent Does Well

The draft covers the core research pipeline — 990 extraction, website review,
and structured output — in a way that maps directly to how you actually work
prospect development at Golden Harvest. The output template is Obsidian-ready,
the prospect rating system (A/B/C/D) gives you immediate triage capability,
and the operating principles enforce the accuracy-over-speed discipline that
grant research demands.

## Critical Gaps and Honest Problems

### 1. The ProPublica API Access Problem

The agent instructs itself to check ProPublica Nonprofit Explorer, but in a
Claude Code subagent context, **web access depends on your network configuration
and available MCP servers.** If you're running this in a sandboxed environment
without web access (as is the case in some Claude Code setups), the agent
cannot actually fetch 990 data live.

**Options to resolve:**
- Configure an MCP server that provides ProPublica API access (their API is
  free and well-documented: https://projects.propublica.org/nonprofits/api)
- Pre-download 990 PDFs and point the agent at local files in a `/990s/`
  directory within your vault or project
- Use the Grant Assist Walled Garden you're already building (the
  ProPublica-scaffolded PostgreSQL on Vercel/Supabase) as the data source —
  this is probably the right long-term answer but requires that infrastructure
  to be functional first

**This is the single biggest gap.** Without reliable 990 data access, the agent
is writing a template it cannot populate. Your Walled Garden project and this
subagent should be developed in tandem — the Walled Garden becomes the data
layer, the subagent becomes the analysis layer.

### 2. No EDGAR / State Filing Integration

For corporate foundations (like Food Lion Feeds Charitable Foundation or
Bank of America Charitable Foundation — both on your active prospect list),
the 990-PF tells only part of the story. The parent company's SEC filings,
annual CSR reports, and state charity registrations often contain:
- Corporate giving budgets and strategic philanthropic priorities
- ESG commitments that create grant alignment opportunities
- Executive charitable interests (proxy statements list board memberships)

**Suggestion:** Add an optional "Phase 1b: Corporate Intelligence" step that
triggers only for corporate foundations. This could include SEC EDGAR lookup
and CSR report review.

### 3. No Historical Trend Analysis

The current workflow captures a single-year snapshot. But the most actionable
intelligence in 990 research comes from **multi-year trends:**
- Is the foundation's giving growing or contracting?
- Have they recently added or dropped program areas?
- Has leadership turned over (new program officer = new priorities)?
- Are assets being spent down (potential sunsetting foundation)?

ProPublica's API returns multiple years of filings. The agent should be
instructed to pull at least 3 years when available and note directional
trends. A foundation that gave $50K to hunger relief last year but $0 the
two years before tells a very different story than one that's given $50K
annually for a decade.

### 4. No Relationship Mapping Layer

The agent identifies key people but doesn't cross-reference them against:
- Golden Harvest's existing donor/contact database
- Board member overlaps with other foundations you've successfully approached
- LinkedIn or professional network connections
- Feeding America network contacts

This is partly a data access problem (the agent shouldn't touch your CRM
directly), but the output template should at least include a **"Relationship
Mapping Prompts"** section that asks Nathan to check specific names against
his network. The agent can do the research; the human does the relationship
intelligence.

### 5. The Feeding America Network Blind Spot

You serve within a network of 200 food banks. Feeding America maintains
shared intelligence about which foundations fund which food banks. The agent
has no access to this network knowledge. When it researches a foundation
that already funds three other Feeding America food banks, that's critical
context — it means there's proven alignment AND potential competitive
overlap.

**Suggestion:** Create a simple reference file (even a CSV) of known
Feeding America network funders that the agent can Grep against during
research. This doesn't need to be comprehensive — even a top-50 list
would catch the most important overlaps. You could build this from your
own knowledge and network contacts over time.

### 6. No Distinction Between Golden Harvest Prospects and Almoner Clients

The agent mentions both audiences in its operating principles but doesn't
structurally separate the assessment. A $500K corporate foundation with
national food bank funding is a Golden Harvest prospect. A $25K family
foundation that funds local parish food pantries is a TheAlmoner.com
client prospect — the kind of small foundation your Grant Prompt Helper
is designed to help volunteer-run organizations approach.

**Suggestion:** Add a **"Channel Recommendation"** field to the output:
- **Golden Harvest direct** — Nathan pursues through his day job
- **Almoner client referral** — Foundation is better suited as an
  example/template for TheAlmoner.com consulting clients
- **Both** — Foundation has programs at both scales
- **Network referral** — Foundation is outside Golden Harvest's geography
  but relevant to another Feeding America food bank (relationship-building
  opportunity)

### 7. No TEFAP / Government Grant Crosswalk

Your legislative research work already identified TEFAP Farm to Food Bank
grants and Farm Bill funding streams. Some private foundations specifically
fund programs that leverage or match government grants. The agent doesn't
cross-reference private foundation opportunities against government funding
streams, which misses a significant strategic angle.

This may be better handled by a separate "Government Grants" subagent
rather than overloading this one, but the output template should at least
include a field: **"Government Funding Leverage Potential: [Yes/No/Unknown]"**

### 8. The Model Choice Question

The draft specifies `model: sonnet` which is the right default for
cost-efficiency on research tasks. However, for complex 990 analysis —
especially when parsing dense financial tables from PDF extractions —
Opus would produce more reliable results. Consider:
- `model: sonnet` for standard website review and profile collation
- `model: opus` invoked manually for complex 990-PF analysis of large
  foundations with complicated investment portfolios or unusual structures

Alternatively, since you're on claude.ai with Opus access, you might
set `model: inherit` so it uses whatever model your main session is running.

## Structural Suggestions

### Create Companion Files

The agent definition alone isn't enough. For this to work well in practice,
you'd want:

1. **`/references/prospect-rating-criteria.md`** — Expanded rubric for the
   A/B/C/D ratings with specific examples from Golden Harvest's history.
   What made Food Lion Feeds an A prospect? What made a past foundation a D?
   This grounds the agent's judgment.

2. **`/references/golden-harvest-profile.md`** — A concise fact sheet about
   Golden Harvest (service area counties, annual budget, program areas,
   current strategic priorities, existing foundation funders) that the agent
   can reference. Without this, it's researching in a vacuum.

3. **`/references/feeding-america-funders.csv`** — The network funder
   reference file described in Gap #5 above.

4. **`/templates/prospect-profile-template.md`** — The output template
   extracted into its own file so it can be iterated independently of the
   agent prompt. The agent instructions would say "Use the template at
   /templates/prospect-profile-template.md" rather than embedding it.

### Consider a Two-Agent Pipeline

The single agent is doing quite a lot: data retrieval, analysis, and
report generation. Following the PubNub pipeline pattern from the
best practices literature, consider splitting this into:

1. **grant-researcher** — Does the raw data gathering (990 extraction,
   website scraping, fact collection). Returns structured JSON or
   a raw data file. Tools: Read, Bash, Grep (web-access MCP if available).

2. **grant-analyst** — Takes the researcher's output and produces the
   evaluated prospect profile with ratings, strategic notes, and
   recommendations. Tools: Read, Write. Model: Opus for analytical quality.

This separation means the researcher can be re-run cheaply against new
data without re-running the analysis, and the analyst can be pointed at
multiple researcher outputs for batch comparison. It also keeps each
agent's context window cleaner.

### Integration with Your Existing Infrastructure

The agent should eventually connect to:
- **Grant Assist Walled Garden** (Vercel/Supabase) — as its primary data source
- **Obsidian vault** — as its output destination (your discretion protocols
  would route Golden Harvest outputs to the work vault, Almoner outputs
  to the personal/ministry vault)
- **Kit (ConvertKit)** — not directly, but the Almoner client prospect
  profiles could feed your consulting pipeline
- **OverSteward repo** — the agent definition itself lives here and benefits
  from version control

## The Honest Assessment

This is a solid first draft for a subagent that addresses a real, recurring
need in your work. The biggest risk isn't the agent design — it's the
**data access layer.** Without reliable, programmatic access to 990 data
(either via API, local files, or your Walled Garden), the agent is an
analyst without source material.

My recommendation for tomorrow's workshop:

1. **Accept the agent definition as a working draft** — refine the prompt
   language and output template based on what you know works in your
   prospect research.

2. **Prioritize the data access question** — decide whether to build the
   ProPublica MCP server, populate a local 990 directory, or push the
   Walled Garden forward. This is the gating dependency.

3. **Build the companion reference files** — especially the Golden Harvest
   profile and the prospect rating criteria. These are quick wins that
   dramatically improve the agent's output quality.

4. **Defer the two-agent split** — until you've tested the single agent
   and found its context window genuinely overloaded. Premature architecture
   is a known pattern to watch for.

The agent is well-conceived. Now it needs infrastructure beneath it and
testing ahead of it.
