ABOUTME: Canonical PR workflow checklist for all projects under chestertron stewardship.
ABOUTME: Sourced into ~/.claude/CLAUDE.md and any project CLAUDE.md that wants the rules inline.

# PR Workflow

**All changes flow through PRs. PRs are the project's task board.**

- **Scope first.** Before writing code, state: (a) branch name, (b) PR title, (c) 1-3 bullet scope. If unclear, scope isn't ready
- **One PR = one logical change.** If implementation outgrows description, stop and split
- **Never commit directly to main/master.** Branch protection enforces this
- **Never use `--admin` to bypass CI.** Wait for checks
- **Draft PRs for exploration.** Convert to ready when scope is clear
- **Write a trajectory note before opening the PR**, at `<repo>/documentation/trajectories/YYYY-MM-DD-PR<N>.md`. Use the schema in OverSteward `documentation/trajectories/TEMPLATE.md`. Captures what worked, what didn't, and what was learned — input artifact for the review-fork subagent (Fiscus epic #25).
- **Branch naming:** `feat/short-description`, `fix/short-description`, `docs/short-description`
- `gh pr list` replaces checking todo files for project status

## Inert controls

A control the passing state shares with the forgotten state is not a control. Two
shapes recur; both pass every test and change no behaviour.

- **A guard that can be satisfied by doing nothing is inert.** Fail closed, and
  force a recorded decision *in the same diff*. If "handled correctly" and "never
  noticed" produce the same output, the guard is decoration (grantspider#2101)
- **A prohibition is inert while the same document still prescribes the forbidden
  form.** Before calling a doctrine fix complete, `grep` the *whole* document —
  and every deployed byte-copy of it — for the form you just forbade. An agent
  following the surviving instruction reproduces the bug the rule was written to
  stop (oversteward#297)
- **A merged watchdog is not a live watchdog.** Detection code, its host install
  (the timer / cron / hook that actually runs it), and the instrumentation the
  probe reads are three separate deliveries — merging the first while assuming
  the other two is how a monitor reports the same silence as a healthy estate.
  Before calling a supervisor deployed, verify all three: the code is merged,
  the host runs it on schedule, and a forced failure visibly alerts
  (oversteward#118, #244, #271, #351)
- **A comment asserting an invariant is part of the security surface.** Prose
  that declares an exemption safe ("this path never receives user input", "the
  fixture makes this impossible") suppresses the very scrutiny that would catch
  its violation — every later reader, including the one adding tests, stops
  checking there. When you write or meet such a comment: either the claim is
  enforced by a test or a guard, or the comment must say it is *unverified*.
  Touching code whose safety comment you rely on obliges you to re-verify the
  claim, not cite it (oversteward#295, aigranthelper#1441, #1555, fiscus#102)
