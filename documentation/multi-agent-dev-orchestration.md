# Multi-Agent Orchestration for Development Projects
**House of Krupa — AI-Assistants Reference**
*Drafted: April 2026*

---

## Context: What Prompted This

Golden Harvest's board chair launched **Creo AI** (getcreo.ai), an Augusta-based AI marketing startup that pairs human strategists with AI production agents to deliver enterprise-level marketing for small businesses. Internally, the operation runs on four coordinated OpenAI agents: one Project Director and three specialist agents operating in tandem across client deliverables.

The CEO characterized it as "training employees." This framing is instructive — and partially wrong in ways worth understanding.

---

## What Creo AI Is Actually Doing

- **Model:** Managed marketing service. Human accountability (Business Lead + Creative Lead per client) wrapped around AI production capacity.
- **Internal architecture:** Project Director agent holds client voice, goals, and content calendar; decomposes work into discrete deliverables routed to specialist agents (social, email, web copy, pipeline).
- **Client-facing product:** Consistency. They solve the "flurry of posts then radio silence" problem small businesses have. The agents are how the *team* works, not what the client sees.
- **Quality gate:** Human review. Strategists approve agent output before delivery.

**The "training employees" misconception:** Agents do not learn persistently between sessions. What Creo AI has actually built is a sophisticated *prompt and workflow architecture*. The intelligence lives in the system design, not the agents themselves. When the system breaks down — and it will — the people running it may not know why, because they think they trained the agents rather than designed the prompts.

---

## Competitive Assessment

### Threat to Grant Helper Pro: Low (present), Monitor (medium-term)
Creo AI is Augusta-local, focused on digital marketing, and serves small businesses. No current overlap with grant writing or nonprofit fundraising. However, given their CSRA base and service-area expansion plans (Greenville, Chattanooga), a grant writing service line is plausible within 18–24 months if they follow the natural adjacency to nonprofit clients.

**Action:** No defensive move required now. Watch their service expansion.

### Threat to TheAlmoner.com Consulting: Minimal
Different buyer, different problem, different value proposition. Creo AI sells marketing execution to for-profit small businesses. TheAlmoner.com sells fundraising capacity and CST-grounded strategy to nonprofits. The audiences do not overlap meaningfully.

### Signal Worth Noting
Board members and donors will hear about Creo AI and will ask questions about whether Golden Harvest is "doing AI." This is a positioning problem, not a capability problem. Be prepared with a clear, non-defensive answer about how AI is already integrated into development operations.

---

## The Development Opportunity

The Creo AI architecture is directly portable to the House of Krupa's multi-project development context — with one significant advantage: **Gaudí already exists as a quality gate**.

Creo AI's agents produce content that humans review. A House of Krupa development orchestration would produce code that Gaudí checks architecturally before acceptance. That is a more mature and defensible system than what Creo AI is running.

### Active Projects Requiring Orchestration
| Project | Domain | Current Status |
|---|---|---|
| Grant Helper Pro | Django/Railway/Neon, pgvector | Landing page first; full build sequenced after consulting funnel activation |
| Gaudí | Python, open-source linter, PyPI | v0.1.0 scaffold complete, 11 language packs, 82+ rules |
| TheAlmoner.com | WordPress, content, consulting funnel | Funnel live; lead activation phase |
| Chestertron | Worldbuilding, Catholic sci-fi | Active collaboration, long-horizon |

---

## Recommended Architecture

### Tier 1: Lightweight (Build This Week)

A **Project State File** — a structured Markdown document that opens every Claude Code session with current context. This is the minimum viable version of what Creo AI has built, and it costs an afternoon.

**Template structure:**

```markdown
# House of Krupa — Development State
*Last updated: [DATE]*

## Active Priorities (Ranked)
1. [Current #1 — e.g., "Food Lion Feeds follow-up + Grant Helper Pro landing page"]
2. [Current #2]
3. [Current #3]

## Workstream Status
### Grant Helper Pro
- Last session: [what was done]
- Next action: [specific next step]
- Blockers: [if any]

### Gaudí
- Last session: [what was done]
- Next action: [specific next step]
- Open decisions: [e.g., "Rule sourcing from Release It! — chapter 5 pending"]

### TheAlmoner.com
- Last session: [what was done]
- Next action: [specific next step]

## Open Architectural Decisions
- [Decision, options, deadline or trigger for resolution]

## Gaudí Gate Status
- Last check run: [date]
- Outstanding violations: [count or "clean"]
```

Drop this file into OverSteward (or the relevant Claude Code project) and open every session by handing it to the agent: *"Here is the current project state. Resume from here."*

**This solves 70% of the context-switching continuity problem at 10% of the build cost.**

---

### Tier 2: Full Orchestration (Build After First Consulting Engagement)

Once the consulting funnel has produced its first paying client, the full architecture becomes worth the build investment.

**Project Director Agent**
- Holds full House of Krupa workstream state
- Opens each session with a structured brief
- Decomposes intent into discrete, sequenced tasks
- Routes tasks to appropriate specialist agent
- Tracks decisions and open items across sessions
- Integrates with OverSteward memory substrate

**Specialist Agents**
| Agent | Scope |
|---|---|
| Backend Dev | Django, Railway, Neon/pgvector, Grant Helper Pro |
| Linter/Architecture | Gaudí rule-writing, Python AST, PyPI prep |
| Content | TheAlmoner.com editorial, Kit sequences, Substack |
| Worldbuilding | Chestertron canon, CST constraint checking |

**Gaudí as Quality Gate**
- All code output from Backend Dev agent passes through `gaudi check` before acceptance
- Violations logged; Project Director agent holds violation history as context
- This is the architectural differentiator Creo AI does not have

**OverSteward as Memory Substrate**
- GitHub-backed shared memory repo
- Survives session boundaries
- Cross-environment: Claude Code, Obsidian, future MCP integrations

---

## Implementation Sequence

```
Week 1:   Draft Project State File → drop into AI-Assistants
          Open next Claude Code session with it; iterate the template

Month 1:  Activate Food Lion Feeds lead + Feeding America contact
          Grant Helper Pro landing page live

Month 2+: First consulting engagement lands
          Begin scoping Project Director agent prompt architecture
          Gaudí reaches v0.1.0 PyPI publication

Quarter 3: Full multi-agent orchestration build
           Gaudí as enforced quality gate integrated into dev workflow
```

---

## Key Principle

> What Creo AI has that the House of Krupa does not yet have is *operational consistency* — the system prevents the "radio silence" failure mode. For the House of Krupa, the analogous failure mode is context loss between sessions: each session restarts cold, the Ideation/Learner profile means strong starts with uneven follow-through, and workstreams drift without a structure that holds them.

> The Project State File is not just a development efficiency tool. It is a **discipline prosthetic** — encoding the order and continuity that the Ideation/Learner profile does not generate naturally. Design it for your actual work patterns, not an idealized version of them.

---

## Related Files
- `OverSteward/` — cross-project memory architecture
- `gaudi/` — `github.com/nkrupa/gaudi`
- `grant-helper-pro/` — Django + Railway + Neon stack
- `thealmoner-funnel/` — Kit sequences, consulting funnel docs
