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

from oversteward.review_collector import ShellCollector
from oversteward.review_input import (
    EXIT_USAGE,
    MAX_ROUNDS,
    ROUND_LEDGER,
    CouldNotLookError,
    RoundCapError,
    assemble,
    derive_round,
    exit_code_for,
    ledger_line,
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
    parser.add_argument(
        "--round",
        type=int,
        default=None,
        help=f"confirm the round this input serves; derived from {ROUND_LEDGER} when omitted",
    )
    parser.add_argument(
        "--restart-rounds",
        default="",
        metavar="REASON",
        help="begin the round count again at 1 — honoured only when the merge base has moved; printed in the header",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="re-review only: the commit the last round reviewed; the diff carries what changed since",
    )
    parser.add_argument(
        "--previous-verdict",
        default=None,
        help="re-review only: file inside the reviewed checkout holding the last round's verdict block and findings",
    )
    parser.add_argument(
        "--override-cap",
        default="",
        metavar="REASON",
        help=f"review past the {MAX_ROUNDS}-round cap, recording why in the input header",
    )
    return parser.parse_args(argv)


def _read_optional(path: str | None, root: Path) -> str | None:
    """The verdict file's text, or None when no path was given.

    The file must sit inside the reviewed checkout (``root``), like the input
    the assembler writes there — one fixed base, so the operator's path cannot
    reach outside it. A missing file is a refusal, not a crash.
    """
    if not path:
        return None
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root):
        raise CouldNotLookError(
            f"--previous-verdict must be inside the reviewed checkout {root}; got {resolved}"
        )
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise CouldNotLookError(f"--previous-verdict {path!r} could not be read: {exc}") from exc


def _record_round(ledger_path: Path, ledger: str | None, line: str) -> None:
    """Append this round to the ledger — never truncate; a restart is a line, not a fresh file."""
    prior = ledger or ""
    if prior and not prior.endswith("\n"):
        prior += "\n"
    ledger_path.write_text(prior + line + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = _parse(argv)
    root = Path(args.root).resolve()
    ledger_path = root / ROUND_LEDGER
    collector = ShellCollector(root)
    try:
        previous_verdict = _read_optional(args.previous_verdict, root)
        ledger = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else None
        base_sha = collector.merge_base(args.base)
        if base_sha is None:
            raise CouldNotLookError(f"could not resolve the merge base against {args.base!r}")
        round_number = derive_round(
            ledger,
            args.round,
            base_ref=args.base,
            base_sha=base_sha,
            restart=args.restart_rounds,
        )
        assembled = assemble(
            collector,
            repo=args.repo,
            base=args.base,
            issue=args.issue,
            no_issue=args.no_issue,
            since=args.since,
            round_number=round_number,
            previous_verdict=previous_verdict,
            cap_override=args.override_cap,
            restart_reason=args.restart_rounds,
        )
    except (CouldNotLookError, RoundCapError) as exc:
        sys.stderr.write(f"{GATE} {exc}\n")
        return EXIT_USAGE
    if not assembled.unmeasured:
        # A round counts only when every input was measured: an assembly that
        # could not look is not a review the reviewer can have done, and the
        # operator who repairs the blindness re-runs the same command as the
        # same round.
        _record_round(
            ledger_path,
            ledger,
            ledger_line(
                round_number,
                args.since,
                args.restart_rounds,
                base_ref=args.base,
                base_sha=base_sha,
            ),
        )

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
