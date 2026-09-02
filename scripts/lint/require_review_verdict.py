#!/usr/bin/env python
# ABOUTME: CI gate — a PR body must carry a well-formed, non-BLOCK adversarial-review verdict.
# ABOUTME: Thin shell over oversteward.review_verdict — read a body, print, pick an exit code.

"""Assert a PR carries the adversarial reviewer's verdict (OS#428).

    scripts/lint/require_review_verdict.py --pr 431 --repo NathanKrupa/OverSteward
    scripts/lint/require_review_verdict.py --body-file tests/fixtures/review_verdict/pass.md

Local gates stay primary and CI is the watchdog (Nathan's pre-launch CI law):
the *agent card* is what refuses to open a PR without a verdict, and this is the
cheap deterministic check behind it, for the case where an author skipped the
card.

Exit codes are four-valued (`pr-workflow.md` § Inert controls) — no two outcomes
share a code, because a skip that prints what a pass prints certifies nothing
while looking like a clean run:

* ``0`` — a well-formed ``PASS`` or ``PASS-WITH-FINDINGS``.
* ``1`` — missing, malformed, or ``BLOCK``.
* ``2`` — could not look: the body could not be fetched or read. Never 0, or a
  network blip certifies every PR it touches.
* ``3`` — not applicable: the PR carries no verdict block at all *and* was
  opened at or before :data:`~oversteward.review_verdict.GATE_LIVE_FROM`, so it
  predates the gate (OS#437). Only reachable via ``--pr``, where a creation time
  exists to read; ``--body-file`` is always judged.

The body is judged before the cutoff is consulted (OS#444). Non-retroactivity
excuses a verdict that is *absent*; a predating PR whose body carries an explicit
``BLOCK`` still exits 1, and one carrying a well-formed ``PASS`` still exits 0 —
otherwise the exemption's own sentence, "nothing was judged", would be false.

The negative fixtures live in ``tests/fixtures/review_verdict/`` and each one is
run against this gate by ``tests/review/test_require_review_verdict.py`` — the
check ships with the inputs that make it fail.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Resolve the package from THIS checkout's `src/` — a session worktree's `.venv`
# is a symlink to the primary checkout's, whose `__editable__*.pth` names the
# primary `src/`. Same reasoning as scripts/lint/trajectory_tags.py.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.review_verdict import (  # noqa: E402
    EXIT_COULD_NOT_LOOK,
    EXIT_NOT_APPLICABLE,
    EXIT_OK,
    judge_pull_request,
)

GATE = "review-verdict:"


def _pull_request(repo: str, number: int) -> dict | None:
    """One PR via the REST API — `gh pr view` 500s on Projects-classic here.

    ``None`` means the call could not be made or its answer could not be read,
    which is the caller's exit-2 case. It never means "an empty PR".
    """
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell
            ["gh", "api", f"repos/{repo}/pulls/{number}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="require_review_verdict.py")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", type=int, help="PR number to read via gh")
    source.add_argument("--body-file", help="read the body from this file instead")
    parser.add_argument("--repo", default="NathanKrupa/OverSteward")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    created_at: str | None = None
    if args.body_file:
        try:
            body: str | None = Path(args.body_file).read_text(encoding="utf-8")
        except OSError:
            body = None
    else:
        pull = _pull_request(args.repo, args.pr)
        body = None if pull is None else (pull.get("body") or "")
        created_at = None if pull is None else pull.get("created_at")

    code, message = judge_pull_request(body, created_at)
    stream = sys.stdout if code in (EXIT_OK, EXIT_NOT_APPLICABLE) else sys.stderr
    if code == EXIT_OK:
        stream.write(f"{GATE} {message} — verdict present and not blocking.\n")
    elif code == EXIT_NOT_APPLICABLE:
        stream.write(f"{GATE} NOT APPLICABLE — {message}\n")
    elif code == EXIT_COULD_NOT_LOOK:
        stream.write(f"{GATE} COULD NOT LOOK — {message}. This is not a pass.\n")
    else:
        stream.write(f"{GATE} FAILED — {message}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
