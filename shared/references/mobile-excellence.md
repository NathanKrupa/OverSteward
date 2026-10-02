ABOUTME: Nathan-law 2026-10-02 — every aigranthelper change that touches a page must be mobile-excellent.
ABOUTME: Deployed to ~/.claude/shared/references/ for live AG sessions; aigranthelper-dev.md states the same rule.

# Mobile-excellent acceptance (aigranthelper)

**Nathan-law, 2026-10-02:** every aigranthelper change must be mobile-excellent.
Googlebot indexes mobile-first. "I don't think this is optional… The goal is to
be so good Google can't ignore us."

Before this rule, mobile quality depended on whoever wrote the brief
remembering it. The AG#2229 audit found nearly every public page type broken at
phone width, and no gate or card rule would have caught it.

## The rule

A change to a template, CSS or front-end JS carries this evidence in its PR
body:

- **Widths:** 360, 375 (mobile emulation) and 1280.
- **At each width:** no horizontal overflow; text ≥ 12px; contrast ≥ 4.5:1; no
  non-inline tap target under 24px, and controls ≥ 44px.
- **Desktop unchanged unless intended**, shown by geometry or screenshots at 1280.
- **Measure with `tests/fixtures/browser_page.py`**, the repo's no-network
  Chromium harness.
- **A new public page type joins the CI mobile matrix (AG#40) in the same PR.**
  If AG#40 has not built the matrix yet, add the page type to that issue and
  say so in the PR body.
- **Run Chrome and Lighthouse from the worktree or `/tmp`, never the primary
  checkout:** chrome-launcher on WSL leaves Windows-named profile directories
  in its cwd (measured on AG#2263).

## Where the rule lives

- Dispatch agents: `shared/agents/aigranthelper-dev.md` in OverSteward,
  byte-copied to `.claude/agents/`.
- Live sessions: this file, deployed to both Claude homes with the rest of
  `shared/`. aigranthelper's `CLAUDE.md` loads it once it carries
  `@~/.claude/shared/references/mobile-excellence.md` (AG#2269); until then a
  live session sees the rule only if it reads this file.

`tests/test_agent_cards.py` holds the two statements to the same thresholds.
