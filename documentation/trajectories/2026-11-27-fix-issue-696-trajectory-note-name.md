---
date: 2026-11-27
repo: oversteward
branch: fix/issue-696-trajectory-note-name
issues:
  - oversteward#696
session_kind: dispatch
duration: 120min
reviewer: PASS-WITH-FINDINGS findings=3 tokens=70000
---

# Trajectory — name a trajectory note by its branch, never a predicted PR number

## Context

OS#696: the rule said to name a trajectory note `YYYY-MM-DD-PR<N>.md` before the
PR exists, so `<N>` was always a guess. Any issue or PR filed in the meantime took
the number, and the correction was a commit after the reviewed SHA. That cost four
renames and two review rounds on 2026-11-11. It recurred on 2026-11-27: OS#844
renumbered its note after review, and marketing-manager#5 ran a delta round only
to cover a rename. This note is the first one written under the new rule. It has
no `pr:` line.

## Trajectory

- I found every reader that depends on a note's name. OverSteward has none: the
  trajectory-tags hook's `files:` pattern only requires the date prefix, and the
  dream promotion pass reads front matter only. No GS, AG, wphelper,
  ai-assistants, exchequer or marketing-manager gate reads note names (GS's
  doc-only classifier matches by directory). The only reader that matches by
  name is a Fiscus metric, filed as Fiscus#140.
- I weighed "name by branch and fill `pr:` later" against leaving `pr:` out. A
  `pr:` fill after `gh pr create` is one more commit and push on every PR. In
  repos whose pre-push hook pins `.verify-marker` to HEAD, that push costs a full
  `make verify` each time, which is worse than today, where a correct guess costs
  nothing. So the note leaves `pr:` out: its PR is the one whose diff adds it, and
  `branch:` is the join key.
- Prose alone would be an inert prohibition, so I added a control. The
  trajectory-tags hook now refuses a `pr:` placeholder, meaning any value that is
  not `<repo>#<number>`. Run over OverSteward's corpus, it flags exactly the five
  legacy placeholder notes and nothing else. Those notes are reached only if
  someone edits them.
- I tested 10 mutants against the new check, and each one was killed by a named
  test. The first draft of the unwired-check mutant was a syntax error, so it was
  invalid rather than a kill. I rewrote it and re-ran it.
- Round 1 of the adversarial review came back PASS-WITH-FINDINGS with 3
  findings. The reviewer self-reported 70,000 tokens; the harness counted
  12,038 output, 97,033 cache-creation and 1,469,261 cache-read tokens. The
  findings and their fixes:
  - (defect) pr-workflow claimed that every reader accepts both names, but a
    Fiscus metric does not until Fiscus#140 lands. The sentence now says so.
  - (pin) Nothing pinned the digit after `#`, so I added `oversteward#`. I also
    added fixtures for a comment-only `pr: #TBD`, an indented list under an
    empty `pr:`, and front matter behind a BOM, and made all three shapes red.
  - (doc) The rulings skill still gave the predicted-number reason. It now
    names that reason as one that lasts only until older cards are
    redeployed. Each fix has a red mutant.

## What worked

- [process] Searching every dispatch repo's default and staging refs for the old form before choosing a design — the result decided the design, because one name-dependent reader can be fixed and a gate in another repo would have forced the old name to stay.
- [tooling] Running the new hook over the whole existing corpus — exactly the five known legacy placeholders came back, which is the real-data proof that the check has no false reds on well-formed notes.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [tooling][trivial] My first unwired-check mutant left a syntax error, so pytest reported a collection ERROR and not a kill → remedy: read the ERROR count beside FAILED, as pr-workflow already says.

## What was learned

- [design] A doctrine field that holds a value only known after a later step has to be written after that step, which means another commit, or left out and derived from a join key. Check which of the two a post-review commit costs in each repo's push hook before you choose → promote: none
- [process] To fix a convention, first enumerate every reader of it across the estate, on origin refs. Readers decide which designs are possible, and here only one reader read the name → promote: none

## Tools

- `scripts/lint/trajectory_tags.py` — the hook, run over the existing corpus as a false-red check.
- `scripts/review/assemble_review_input.py` — the reviewer input.

## Open threads

- Fiscus#140: a Fiscus reader still matches notes only by the `-PR<N>.md` name.
- OS#458: the online `pr:`-matches-branch guard has to accept an absent `pr:`, because new notes carry none.
- The canonical `shared/` edits reach other repos and both Claude homes only through the shared deploy after merge.
