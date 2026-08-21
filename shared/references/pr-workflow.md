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
- **A regression test that was never seen red is not a regression test.** A new
  test can pass against the pre-fix code and still read like a guard — two of
  the four in oversteward#312 did. Running the *suite* red proves only that
  some test bites; a passing neighbour hides the vacuous one. Before the fix
  lands, run **each new test individually** against the unfixed code and watch
  it fail for the stated reason; one that passes either way is decoration
  (oversteward#312, grantspider#1999, #2220)

## False greens — a check that reports success must prove it can fail

Ten false greens in eleven weeks: a gate, sweep or probe that passed while
proving nothing, each caught by luck or by a later unrelated failure, none by
design. A green is a *measurement*, and a measurement is only worth its
sensitivity. These five rules make that sensitivity demonstrable.

- **A new check ships with the fixture that makes it fail.** Green against live
  data is not acceptance — it measures the data, not the check. The proof is
  the negative fixture: make the check red on purpose, watch it fail for the
  stated reason, and cite that fixture in the PR. The same duty is continuous
  for anything that alerts — **a canary must assert it can alert on every run,
  because silence is its failure mode** (oversteward#327)
- **Never pipe a gate through `| tail` or `| head`.** The pipeline's exit status
  is the *last* command's, so `make verify 2>&1 | tail -20` reports `tail`'s
  success and a failing verify reads as a pass. This has bitten twice (`make
  verify`, then `gaudi`). Redirect to a file and read it — `cmd > /tmp/out 2>&1;
  rc=$?` — or check `${PIPESTATUS[0]}`. The prohibition covers any filter in the
  final position, `tail` and `head` being the two that actually happened
  (oversteward#327)
- **A uniform result is a suspect result.** When a sweep reports the same
  verdict for every subject, prove it visited distinct subjects before believing
  it. A drift sweep over 16 repos read empty paths from `registry.yaml`,
  resolved all of them against cwd, and printed OK sixteen times — a convincing
  false green that had inspected nothing (oversteward#327)
- **`rc=0` is not a pass on its own.** Some tools exit 0 on usage errors:
  `gaudi check <a> <b>` rejects multiple paths on stderr and still exits 0, and
  `gh pr edit --base` printed a deprecation warning while silently leaving the
  base unchanged. For any tool not *known* to fail loudly, assert on the output
  as well as the code (oversteward#327)
- **A skip must not read as a pass.** "Found nothing" and "could not look" must
  never print or exit the same — a scanner that skips silently when its backend
  is missing certifies nothing while looking identical to a clean run
  (`gitleaks --exit-code=0` on an empty report; `secret_scan.py --staged` with
  no docker). Give the two outcomes different exit codes, as
  `worktree_doctor.py sweep` (2 = could not look, 0 = measured answer) and
  `scripts/lint/gaudi_check_files.py` (2 = gaudi absent) already do
  (oversteward#327)
