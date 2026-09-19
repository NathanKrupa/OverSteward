---
date: 2026-09-18
repo: oversteward
pr: oversteward#513
branch: session/estate-board
issues:
  - none — Nathan's standing ask of 2026-08-28 (memory: project_estate_board_interface), never filed
session_kind: in-session-pickup
duration: "~3h"
reviewer: PASS-WITH-FINDINGS findings=5 tokens=90000
---

# Trajectory — Estate Board read side: decision queue and epic health from gh

## Context

Nathan opened the session with "GitHub connector is on — observe the tools and
build the Estate Board." The board's design was ruled on 2026-08-28: a stateless
page derived from GitHub, showing only what wants his decision plus counts, with
tappable cards that write back through the GitHub connector; and an epic-health
model built *before* the buttons, because the real pain was lines of inquiry
dropping from the queue (GS at 200+ open issues, 27 epics that were only label
prefixes). The connector was the first-ordered step; the read side was second.

## Trajectory

- Observed the tool roster before anything else: `claude mcp list` and ToolSearch
  both show Claude Docs, Drive, Gmail, Calendar, Canva — no GitHub, for the
  second time (2026-08-29 note). `CLAUDE_CODE_OAUTH_TOKEN` unset, so the
  account-level `/v1/mcp_servers` list could not be checked from here. The
  `mcp` artifact capability needs the connector mounted as `mcp__<connector>__*`
  tools in the publishing session, so the write-back cards were blocked for
  the session; the read side was not, and was always first in the plan.
- Probed the real epic model in GS/AG/OS with `gh`: two representations coexist
  — `epic`-titled issues (29 GS, 16 AG, 4 OS) and `epic:<slug>` labels on
  children (19/16/1). Children link by the label and by `#N` mentions in the
  parent's body. A single OR label search (`label:"epic:a","epic:b"`) returns
  every epic-labelled closed issue per repo in one call (GS 114 of 899 closed).
- Built `src/oversteward/board/` on the liveness package's shape — `models`,
  `client` (gh, INNER), `config` (registry → RepoRef), `epics` and `assemble`
  (MIDDLE), `render` — with a thin `scripts/estate_board.py` mapping exit codes
  0/1/2. TDD throughout; each module's mutants run by file with
  `PYTHONDONTWRITEBYTECODE=1`.
- Ran the real estate through the model before rendering: 993 issues, 7 repos,
  4.7s. Two corrections came from the data, not the tests: a parentless label
  whose children are all closed (AG `epic:ontology`) is history, not a
  decision; and "needs scoping" must mean the `needs-scoping` label, as
  `/project-status` counts it, or the two disagree (293 vs 50 for GS).
- A uniform "72 days quiet" across nine epics was checked against distinct
  subjects: 2026-07-08 was a bulk-update day, and the children are genuinely
  quiet since. The uniform figure is real.
- Published the page over the 2026-08-28 draft artifact (same URL, version 2).
- Adversarial review round 1: PASS-WITH-FINDINGS, 5. The substantive one: an
  open epic whose body-named children had all closed *without* the slug label
  read "no children", because the client fetched closed issues only by label.
  Fixed by reading each unfetched ref of an open epic by number (404 and PRs
  are not children); same-repo issue URLs now count as refs; registry errors
  exit 2. Three of the live "childless" epics became "every child is closed"
  (8 done-open, was 3). Republished as version 3.
- Nathan's screenshot of Settings → Connectors showed the row is "GitHub
  Integration" (the repo-sync integration), not the GitHub MCP connector — the
  2026-08-29 hypothesis confirmed.

## What worked

- [design] Following the liveness package's layering verbatim (models / client / config / service / render / thin script with 0-1-2 exit codes) — every architectural question was already answered, so the session spent its time on the model.
- [functional] Running the real estate through the model before writing the renderer — it found two definition errors (history epics as decisions; a scoping count that disagreed with `/project-status`) that no fixture would have.
- [process] The adversarial reviewer ran the script against live GitHub and resolved every "no children" verdict against the issues' bodies — that is how the closed-label-less-child defect surfaced; the author's fixtures all carried the label.
- [tooling] Mutating by file with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` — a same-size mutant restored within the same second had earlier left its `.pyc` behind and made the restored tree read red.
- [process] Proving the secret-scan substitute could fire (a fake AWS key in a scratch repo) before trusting its clean result — the "clean" run was an empty binary exiting 0.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [tooling][minutes] `gh release download` wrote a 0-byte tarball and exited 0; `tar` then produced an empty `gitleaks`, which ran as a no-op shell script and "passed" every scan — the negative fixture caught it → remedy: verify a downloaded binary's size and checksum against the release's checksums file before running it.
- [tooling][minutes] Docker Desktop's daemon returned 500 on `docker info`, so the secret-scan pre-commit hook refused; the classifier then refused `SECRET_SCAN_ALLOW_UNAVAILABLE=1` as a safety bypass → remedy: none needed this time (Docker Desktop had been relaunched minutes earlier and came back), but `secret_scan.py` could fall back to a local `gitleaks` binary of the pinned version — filed as an open thread.
- [process][blocked] The GitHub connector Nathan reported as "on" is not mounted, for the second session running — the write-back cards cannot be observed against a real tool call, so they were not built → remedy: the connector must be the claude.ai *Connector* (Settings → Connectors → GitHub, enabled for Claude Code), and it mounts only at session start; verify with `claude mcp list` before scoping any card work.

## What was learned

- [functional] An epic's motion is its children's, never the parent's own `updatedAt` — a parent moves on every label tweak and comment, so parent motion would hide a stalled line → promote: memory.
- [functional] GitHub's `updatedAt` moves on bulk label sweeps, so "days quiet" measures the last *touch*, not the last *work*; a uniform quiet figure across many epics must be checked against distinct subjects before it is reported → promote: memory.
- [tooling] A downloaded executable that is empty runs as a shell script and exits 0 — `rc=0` from an unverified binary proves nothing; check size and checksum first → promote: doctrine.
- [tooling] A same-size, same-second mutant restore leaves a stale `.pyc` that the interpreter trusts (mtime+size check) — run mutation loops with `PYTHONDONTWRITEBYTECODE=1` → promote: doctrine.
- [process] "GitHub connected to claude.ai" still does not mean the session can call it — verify the `mcp__*` roster, never the claim, before scoping connector-dependent work → promote: memory.

## Tools

- `scripts/estate_board.py` [NEW] — builds the board page from every dispatch-target repo; exit 0/1/2.
- `src/oversteward/board/` [NEW] — models, gh client, registry config, epic health, assembly, render.
- `gh issue list --search 'label:"epic:a","epic:b"'` [used] — one OR search per repo for closed epic children.
- `~/.local/bin/gitleaks` v8.18.4 [NEW on this machine] — local substitute for the docker-hosted scan when the daemon is down; checksum-verified.
- `scripts/review/assemble_review_input.py` + `claude -p --agent adversarial-reviewer` [used].

## Open threads

- The write-back decision cards (answer / dispatch / close-with-reason) wait on the GitHub connector being mounted in a session; one real request per write tool must be observed before any card ships.
- `secret_scan.py` could accept a local `gitleaks` binary of the pinned version when docker is unavailable — the hook is the only secret-scan control (CI does not run one), so a down daemon currently blocks every commit. File as an OverSteward issue.
- `scripts/project_status.py` still carries its own `gh_json` and label vocabulary; a follow-up can have it import `oversteward.board.client` and `models` so the two never drift.
- The board's "In flight" tile counts `agent-in-progress` labels only; joining `claude agents --json` (the draft's intent) is a follow-up.
