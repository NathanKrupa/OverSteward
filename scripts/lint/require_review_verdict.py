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

Exit codes are three-valued (`pr-workflow.md` § Inert controls):

* ``0`` — a well-formed ``PASS`` or ``PASS-WITH-FINDINGS``.
* ``1`` — missing, malformed, or ``BLOCK``.
* ``2`` — could not look: the body could not be fetched or read. Never 0, or a
  network blip certifies every PR it touches.

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
    EXIT_OK,
    judge,
)

GATE = "review-verdict:"


def _body_from_gh(repo: str, number: int) -> str | None:
    """The PR body via the REST API — `gh pr view` 500s on Projects-classic here."""
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
        return json.loads(proc.stdout).get("body") or ""
    except json.JSONDecodeError:
        return None


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="require_review_verdict.py")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", type=int, help="PR number to read via gh")
    source.add_argument("--body-file", help="read the body from this file instead")
    parser.add_argument("--repo", default="NathanKrupa/OverSteward")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    if args.body_file:
        try:
            body: str | None = Path(args.body_file).read_text(encoding="utf-8")
        except OSError:
            body = None
    else:
        body = _body_from_gh(args.repo, args.pr)

    code, message = judge(body)
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    if code == EXIT_OK:
        stream.write(f"{GATE} {message} — verdict present and not blocking.\n")
    elif code == EXIT_COULD_NOT_LOOK:
        stream.write(f"{GATE} COULD NOT LOOK — {message}. This is not a pass.\n")
    else:
        stream.write(f"{GATE} FAILED — {message}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
