ABOUTME: Canonical PR workflow checklist for all projects under chestertron stewardship.
ABOUTME: Sourced into ~/.claude/CLAUDE.md and any project CLAUDE.md that wants the rules inline.

# PR Workflow

**All changes flow through PRs. PRs are the project's task board.**

- **Scope first.** Before writing code, state: (a) branch name, (b) PR title, (c) 1-3 bullet scope. If unclear, scope isn't ready
- **One PR = one logical change.** If implementation outgrows description, stop and split
- **Never commit directly to main/master.** Branch protection enforces this
- **Never use `--admin` to bypass CI.** Wait for checks
- **Draft PRs for exploration.** Convert to ready when scope is clear
- **Run the adversarial reviewer between "tests green" and `gh pr create`**, and paste its verdict block into the PR body. Your `*-dev` agent card carries the exact commands; `shared/agents/adversarial-reviewer.md` is the brief. A `BLOCK` means do not open the PR
- **Write a trajectory note before opening the PR**, at `<repo>/documentation/trajectories/YYYY-MM-DD-PR<N>.md`. Use the schema in OverSteward `documentation/trajectories/TEMPLATE.md`
- **Branch naming:** `feat/short-description`, `fix/short-description`, `docs/short-description`
- `gh pr list` replaces checking todo files for project status

## Inert controls

A control the passing state shares with the forgotten state is not a control.
Each rule below states its mechanism; the incidents behind them are in the
trajectory corpus, not here.

- **A guard that can be satisfied by doing nothing is inert.** Fail closed, and force a recorded decision *in the same diff*. If "handled correctly" and "never noticed" produce the same output, the guard is decoration
- **A prohibition is inert while the same document still prescribes the forbidden form.** Before calling a doctrine fix complete, `grep` the *whole* document — and every deployed byte-copy of it — for the form you just forbade
- **A merged watchdog is not a live watchdog.** Detection code, its host install (the timer / cron / hook that actually runs it), and the instrumentation the probe reads are three separate deliveries. Before calling a supervisor deployed, verify all three: the code is merged, the host runs it on schedule, and a forced failure visibly alerts
- **A comment asserting an invariant is part of the security surface.** Prose declaring an exemption safe suppresses the scrutiny that would catch its violation. Either the claim is enforced by a test or a guard, or the comment must say it is *unverified*. Touching code whose safety comment you rely on obliges you to re-verify the claim, not cite it
- **A regression test that was never seen red is not a regression test.** Before the fix lands, run **each new test individually** against the unfixed code and watch it fail for the stated reason. A test red only because its import does not exist yet proves the *module* is new, not that the guard bites — an ImportError red must not be reported as seen-red on its own. After the implementation exists, **mutate it** (invert the guard, move the check after the call, delete the filter) and re-run each new test: the ones that stay green are pins or decoration, and must be rewritten or declared as invariant pins in the PR body. The adversarial reviewer performs this mutation pass independently; your own is still owed

## False greens — a check that reports success must prove it can fail

A green is a *measurement*, and a measurement is only worth its sensitivity.
These rules make that sensitivity demonstrable.

- **A new check ships with the fixture that makes it fail.** Green against live data measures the data, not the check. The proof is the negative fixture: make the check red on purpose, watch it fail for the stated reason, and cite that fixture in the PR. **A canary must assert it can alert on every run**, because silence is its failure mode
- **Never pipe a gate through `| tail` or `| head`.** The pipeline's exit status is the *last* command's, so a failing gate reads as a pass. Redirect to a file and read it — `cmd > /tmp/out 2>&1; rc=$?` — or check `${PIPESTATUS[0]}`. The prohibition covers any filter in the final position. `guard_gate_pipe.py` refuses the shape at the Bash tool; it sees only Claude Code, so a Makefile, a terminal or a CI runner still needs the rule
- **A uniform result is a suspect result.** When a sweep reports the same verdict for every subject, prove it visited distinct subjects before believing it
- **`rc=0` is not a pass on its own.** Some tools exit 0 on usage errors, and some ignore the severities you asked them to gate on. For any tool not *known* to fail loudly, assert on the output as well as the code
- **A skip must not read as a pass.** "Found nothing" and "could not look" must never print or exit the same. Give the two outcomes different exit codes — 2 for "could not look", as `worktree_doctor.py sweep`, `gaudi_check_files.py`, `check_hooks_path.py` and `sync_repos.py` do
- **A gate that applies a fix must assert the fixed bytes are the ones being certified.** A formatter or generated file rewritten *during* verify leaves the rewrite unstaged, so the marker is written at HEAD and the push ships unformatted bytes. Assert the tracked tree equals HEAD and fail *before* any marker is written; `require_formatted_commit.py` and `format_staged.py` are the sanctioned members
- **A gate run in a worktree certifies whichever tree Python imports — prove it is the worktree.** The shared `.venv`'s editable `.pth` points at the primary checkout, so without an **absolute** `PYTHONPATH=<worktree>/src` every gate silently measures the primary tree. Before the first gate and after any `cd`, print the resolved path and read it: `.venv/bin/python -c "import <pkg>; print(<pkg>.__file__)"`. A repo whose cross-repo siblings are MetaPathFinder installs (aigranthelper) must reinstall them into the worktree's own venv instead — `PYTHONPATH` cannot shadow those
