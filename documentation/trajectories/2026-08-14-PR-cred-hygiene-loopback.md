---
date: 2026-08-14
repo: oversteward
pr: oversteward#TBD
branch: session/cred-hygiene-loopback
issues:
  - oversteward#355
session_kind: in-session-pickup
duration: ~45min
---

# Trajectory — loopback test-bench exemption in the credential-hygiene control

## Context

OS#355: the blunt `*DATABASE_URL*` controls blocked legitimate local-bench
commands, a measured 5x GS recurrence. Nathan approved the fix with an explicit
constraint — the exemption must not open a credential-leak hole; that is a fail
state. The control surface turned out to be two layers: the
`check_db_access.py` PreToolUse hook AND two `settings.json` deny globs that
fired before the hook could apply any judgment.

## Trajectory

- Read the whole hook before touching it; found the deny-glob layer only when a
  live probe was refused *without* the hook's block message — the glob fired
  first, meaning the hook's existing nuance was unreachable for this shape.
- Chose the coverage-preserving shape: the hook becomes SOLE owner of the
  `DATABASE_URL` policy (blocks every reference, stricter than its old
  read-word heuristic and equal to the glob), with one carve-out — every token
  must be a literal assignment whose `urlsplit` hostname is exactly
  localhost/127.0.0.1/::1, with `$`/backtick/backslash excluded so expansion
  cannot smuggle a value. Then retired the two deny globs.
- Exemption applies only to the LAST detector in main(); `.env` reads,
  env dumps, `$SECRET` echoes, psycopg/psql shapes all run first and are
  untouched.
- Built the negative-control matrix INTO the hook (`--self-test`, 22 cases,
  each piped through main() in a subprocess) because `~/.claude/hooks/` is not
  a git repo — controls that live apart from this guard would never run.
- Live end-to-end probes through the real permission layer: loopback literal
  runs; Neon-shaped, `localhost.evil.com`, and grep-pattern shapes all still
  refuse.
- This PR carries the doctrine half: credential-hygiene.md now describes the
  two-layer model and the exemption's exact contract.

## What worked

- [process] Probing the live control instead of trusting the code read — the settings.json deny-glob layer was invisible in the hook file and surfaced only because a "should now pass" probe still refused, with a different error shape.
- [design] Self-test embedded in the guard itself — the negative controls travel with the only copy of the control, runnable with zero setup.
- [design] `urlsplit`-based hostname extraction instead of substring matching — the userinfo and prefix-host attack shapes are handled by the URL grammar, not by enumerating tricks.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [tooling][trivial] The tightened hook immediately blocked my own `grep DATABASE_URL settings.json` probes — as designed, but it forced the in-process/Read path for the settings edit → remedy: none; that is the control working.

## What was learned

- [design] A permission deny-glob and a PreToolUse hook on the same shape means the glob decides and the hook's judgment is dead code — when adding nuance, the blunt layer must be retired in the same change or the nuance never runs → promote: doctrine (this PR's credential-hygiene.md edit).
- [process] A security-control carve-out should be provable from a closed-world argument ("a literal the agent typed cannot leak anything the transcript does not already contain"), not from enumerated attack cases — the enumeration then becomes the regression suite, not the design → promote: lessons.jsonl.

## Tools

- `check_db_access.py --self-test` [NEW] — 22-case negative-control matrix inside the hook.
- Live Bash probes through the real permission chain [used] — end-to-end verification of both allow and refuse paths.

## Open threads

- Deploy the doctrine byte-copy to both Claude homes (WSL + Windows) on merge.
- The hook still has no canonical repo home; if it grows again, canonicalise it into OverSteward `shared/` with the deploy sweep.
