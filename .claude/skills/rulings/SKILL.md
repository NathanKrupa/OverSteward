---
name: rulings
description: "Put every decision waiting on Nathan to him as click-through pop-ups, four at a time with options, then record and post each answer. Gathers `needs-input` issues, unlabelled decision blocks in issue bodies and the questions the session state lists as unanswered, verifies each is still open, and asks the most blocking first. Use when Nathan asks \"what are the questions for me\", \"pop them up\", \"let me click through the decisions\", \"what do you need from me\", or runs /rulings. For a plain list use /questions; for one typed answer on one issue use /answer."
---

# /rulings — his decisions, four at a time

## Why this exists

Measured on 2026-11-21, the night this was first done by hand:

- One sitting took **28 rulings in seven pop-ups**. The oldest of those questions had been open since 2026-10-03.
- Only **4 of the 28** sat on an issue labelled `needs-input`, which is all `/questions` lists. The rest were decision blocks in issue bodies, agent reports and session notes, none of which Nathan reads.
- The first list handed to him named **four questions that were already answered**, two of them that same evening in another session. An answered question put again costs him a click and risks a second ruling that contradicts the first.
- "About twenty" questions became more than forty once each was split into one decision.

So this skill gathers from every source, verifies before it asks, and writes each answer down before the next pop-up.

Run from the **OverSteward** primary checkout:

```bash
cd /home/natha/OverSteward
TARGETS="$(.venv/bin/python scripts/registry.py dispatch-targets)"   # OverSteward is among them
```

## Phase 1 — gather (measure, never recall)

Four sources. A candidate is one decision, with the place it was asked.

1. **Labelled questions.**
   ```bash
   for r in $TARGETS; do gh issue list -R NathanKrupa/$r --label needs-input --state open \
     --json number,title -q ".[]|\"$r#\(.number) \(.title)\""; done
   ```
2. **Decision blocks nobody labelled.** Run once per phrase: `Decision needed`, `Needs Nathan`, `Open question`, `needs a ruling`.
   ```bash
   gh search issues --owner NathanKrupa --state open --match body "Decision needed" \
     --json repository,number,title --limit 100 -q '.[]|"\(.repository.name)#\(.number) \(.title)"'
   ```
3. **The session state.** Its snapshot lists questions with no recorded answer, and a live session writes its own as it goes.
   ```bash
   grep -n -i -E "for nathan|waiting on nathan|still to ask|unanswered" SESSION_STATE.md
   ```
4. **This session.** Any decision it is itself holding.

Operator steps are not rulings. A step only he can perform stays in Todoist (`scripts/operator_steps.py list`).

## Phase 2 — verify each is still open

Do this for every candidate **before the first pop-up**.

- Read the issue's state, labels and last comments. Closed is dropped. A comment that records his answer after the question ("**Nathan, …**", "[answering …") means answered.
  ```bash
  gh issue view <n> -R NathanKrupa/<repo> --json state,labels,comments \
    -q '{state, labels: [.labels[].name], last: (.comments | map(.body[0:200]) | .[-3:])}'
  ```
- Search `SESSION_STATE.md` for the issue number **below** the line that raised the question. A later `NATHAN (verbatim)` line may answer it.
- If the session state shows another session appending today, its questions are its own. Put one to him only when nothing there answers it, and tell that session afterwards.
- Check whether a standing law already answers it: search `~/.claude/projects/-home-natha-OverSteward/memory/MEMORY_FULL.md` for the subject.
- Drop what events overtook: the thing shipped, or the measurement that decides it has not read out yet.

State the count before asking: candidates, already answered, overtaken, to ask.

## Phase 3 — write each question

- **One decision per question.** "Four data-model questions" is four questions.
- **Fetch the question's own text.** Never phrase a question from a summary of it.
- **It must stand alone.** He may see only the dialog. Name the issue, say what is true today, and say what each choice causes, in his terms and not the code's.
- **Options come from the issue** where it lists them. Never invent an option for a call that is his domain: which bodies count as funders, what a food pantry needs. Offer the issue's choices; "Other" is always added for him.
- **Two to four options.** Add "not yet" or "hold" where deferring is an honest choice.
- **Recommend only with a stated basis.** A recommended option goes first, ends "(Recommended)", and its description says why. A domain call gets no recommendation.
- **Name what a yes would grant.** A spend, a promote, a production read or write, or a customer-facing change is named in the question. His click is his word for what the question said and nothing wider.
- A header is at most 12 characters.

## Phase 4 — ask, most blocking first

Order:

1. what a lane in flight is stopped on;
2. what the next promote or a dated event needs;
3. queued epics;
4. housekeeping, such as branch deletions;
5. proposals.

- Four questions per `AskUserQuestion` call, grouped so each pop-up is one subject.
- Tell him the total first, and that closing a pop-up stops the run.
- **After every pop-up, before the next, append the answers to the ledger**: `~/.local/state/oversteward/rulings/<UTC date>.md`. A choice is recorded by its label. A typed answer is quoted verbatim, and any reading of it is marked as the session's.
- A typed answer can be a correction, a new instruction or a refusal. Read it and follow it; never fold it into the nearest option.
- When he says stop, stop. The rest is carried, not squeezed in.
- With no pop-up tool (a headless run, a phone relay), print the same four questions as a numbered list with lettered options and take a typed reply.

## Phase 5 — record and post

1. **Session state.** Append one section to `SESSION_STATE.md` with `cat >>`, never a rewrite: each answer on a line, then the unasked questions in order with their prepared options.
2. **Each ruling on its issue**, as a comment written to a file and posted with `gh issue comment <n> -R NathanKrupa/<repo> --body-file <file>`:
   - open with `**Nathan, <UTC date>, by click-through in an OverSteward session:**`;
   - give his choice, and say what was offered and not chosen;
   - never write a bare `@` mention;
   - in a public repo (OverSteward, gaudi), describe nothing private.
3. **Labels.** If this session holds the issue's lane, swap the labels as `/answer` step 5 does. If another session holds it, change no label and tell that session.
4. **New issues an answer calls for.** Before filing one, check that no agent is in flight in that repo (`git -C /home/natha/<repo> worktree list`, `gh pr list -R NathanKrupa/<repo> --state open`). An issue filed mid-flight takes the PR number an agent has already predicted (OS#696). If one is in flight, list the issue as owed in the session state for the lane that owns the repo.
5. **An answer that authorizes an action** (a read, a run) is acted on or recorded as owed. It covers what the question named.
6. **A ruling that reaches beyond its issue** is a standing law. Say so in the session-state section; the dream cycle folds it into memory. Never hand-edit `MEMORY.md`.

## Phase 6 — report

One short table: asked, answered, typed, carried. Then where the answers are recorded and what they leave owed.

## Rules

- **Verify before asking.** An already-answered question put again is the defect this skill exists to prevent.
- **Write before the next pop-up.** An answer held only in context is lost to a compaction or a laptop sleep.
- **Record the question with the answer.** A click means nothing without the words it answered.
- **No relabel, no dispatch and no new issue** in a lane another session holds.
- **Never on a Sunday** unless he opens the session and asks.

## Related

- `/questions` — the read-only list of `needs-input` issues.
- `/answer <repo> <n>` — one typed answer on one issue, with the label swap.
- `/stepping-away` — its Phase 1 step 5 lists the decisions a run would hit; this skill is how they are put to him.
