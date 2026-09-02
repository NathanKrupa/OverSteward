#!/usr/bin/env python
# ABOUTME: Assembles the adversarial reviewer's inputs; the author runs this, never the prompt.
# ABOUTME: Thin shell over oversteward.review_input — parse argv, print, pick an exit code.

"""Gather the adversarial reviewer's inputs deterministically (OS#428).

    scripts/review/assemble_review_input.py --issue 428 > /tmp/review-input.md

The author agent runs this and hands the *file* to the reviewer. It never
writes the reviewer's prompt: a captured or hurried author who summarised the
diff, dropped a test file, or skipped the gaudi run would degrade the
fresh-context guarantee without leaving a trace.

Exit codes are three-valued (`pr-workflow.md` § Inert controls):

* ``0`` — every input measured. Safe to review.
* ``1`` — usage: no diff to review, no base ref, no recorded decision on the issue.
* ``2`` — could not look: an input was unavailable. The document is still written
  (with the gap named in its header), because a reviewer told "gaudi did not run"
  is useful and a reviewer silently handed no findings is not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve the package from THIS checkout's `src/`, ahead of whatever the shared
# venv's editable install points at: a session worktree's `.venv` is a symlink to
# the primary checkout's, whose `__editable__*.pth` names the *primary* `src/`.
# Assembling review input with the primary checkout's copy of this service would
# review one tree using another tree's rules. Same reasoning as
# scripts/lint/trajectory_tags.py.
sys.path.insert(  # noqa: STRUCT-010
    0, str(Path(__file__).resolve().parents[2] / "src")
)

from oversteward.review_collector import ShellCollector  # noqa: E402
from oversteward.review_input import (  # noqa: E402
    EXIT_USAGE,
    CouldNotLookError,
    assemble,
    exit_code_for,
    render,
)

GATE = "review-input:"


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="assemble_review_input.py", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--repo", default="NathanKrupa/OverSteward", help="owner/repo for gh")
    parser.add_argument("--base", default="origin/master", help="base ref the diff is taken from")
    parser.add_argument("--root", default=".", help="checkout to read (default: cwd)")
    parser.add_argument("--issue", type=int, default=None, help="issue number this change closes")
    parser.add_argument(
        "--no-issue",
        action="store_true",
        help="record deliberately that this change closes no issue",
    )
    parser.add_argument("--out", default=None, help="write here instead of stdout")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    root = Path(args.root).resolve()
    try:
        assembled = assemble(
            ShellCollector(root),
            repo=args.repo,
            base=args.base,
            issue=args.issue,
            no_issue=args.no_issue,
        )
    except CouldNotLookError as exc:
        sys.stderr.write(f"{GATE} {exc}\n")
        return EXIT_USAGE

    document = render(assembled)
    if args.out:
        Path(args.out).write_text(document, encoding="utf-8")
        sys.stderr.write(f"{GATE} wrote {args.out}\n")
    else:
        sys.stdout.write(document)

    code = exit_code_for(assembled)
    if assembled.unmeasured:
        sys.stderr.write(
            f"{GATE} UNMEASURED: {', '.join(assembled.unmeasured)} — "
            "the reviewer must be told, not handed a clean-looking blank.\n"
        )
    else:
        sys.stderr.write(f"{GATE} all {len(assembled.sections)} inputs measured.\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
