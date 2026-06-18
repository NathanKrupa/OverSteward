#!/usr/bin/env python3
# ABOUTME: The Telegraph's relay primitive — file an issue into a sibling repo's queue.
# ABOUTME: Canonical in OverSteward shared/scripts/telegraph/; portable (stdlib-only), gh-backed.
"""File a cross-repo issue with the estate's labeling convention.

This is the shared convergence point of The Telegraph (see
``documentation/designs/the-telegraph.md`` §4): the one sanctioned way for an
agent in one repo to put work into another repo's queue, instead of routing it
through Nathan by hand.

Two callers, one primitive:
- **Ambient** cross-repo filing lands as ``needs-scoping`` (the default) — the
  human gate stays per-issue.
- The **Epic Conductor** calls the same function with ``label="ready-for-agent"``
  inside a Nathan-blessed epic — the gate has already moved to plan-approval.

Every filed issue carries a ``from:<source-repo>`` provenance label and a
back-link footer, so cross-repo work is queryable and traceable.

Pure composition is split from the ``gh`` subprocess call so the logic is
unit-tested without GitHub. Stdlib-only by design: this file is byte-copied to
repos that do not have the ``oversteward`` package installed.
"""

from __future__ import annotations

import argparse
import subprocess  # list-form argv, never shell
import sys
from collections.abc import Callable, Sequence

DEFAULT_LABEL = "needs-scoping"


def compose_labels(label: str, source_repo: str | None) -> list[str]:
    """Primary label plus a ``from:<source>`` provenance tag when known."""
    if not label:
        raise ValueError("primary label must be non-empty")
    labels = [label]
    if source_repo:
        labels.append(f"from:{source_repo}")
    return labels


def compose_body(body: str, source_repo: str | None, backlink: str | None) -> str:
    """Append a provenance footer naming the filer and (if known) the origin."""
    if not source_repo:
        return body
    origin = backlink or "(no link provided)"
    footer = f"\n\n---\nFiled by the {source_repo} agent via The Telegraph. Origin: {origin}"
    return body + footer


def build_issue_argv(
    target_repo: str, title: str, body: str, labels: Sequence[str]
) -> list[str]:
    """Build the ``gh issue create`` argv (list form, no shell)."""
    if not target_repo:
        raise ValueError("target_repo must be non-empty")
    if not title:
        raise ValueError("title must be non-empty")
    argv = [
        "gh", "issue", "create",
        "--repo", target_repo,
        "--title", title,
        "--body", body,
    ]
    for label in labels:
        argv += ["--label", label]
    return argv


def parse_issue_url(stdout: str) -> str:
    """Return the issue URL ``gh`` prints (the last https line of its output)."""
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("https://"):
            return stripped
    raise ValueError(f"no issue URL found in gh output: {stdout!r}")


def _run_gh(argv: Sequence[str]) -> str:
    """Run gh and return stdout; raises CalledProcessError on a non-zero exit."""
    result = subprocess.run(
        list(argv), capture_output=True, text=True, check=True
    )
    return result.stdout


def file_cross_repo_issue(
    target_repo: str,
    title: str,
    body: str,
    *,
    label: str = DEFAULT_LABEL,
    source_repo: str | None = None,
    backlink: str | None = None,
    run: Callable[[Sequence[str]], str] | None = None,
) -> str:
    """File an issue into ``target_repo`` and return its URL.

    ``run`` is the gh invoker, injected for testing; defaults to the real one.
    """
    runner = run or _run_gh
    labels = compose_labels(label, source_repo)
    full_body = compose_body(body, source_repo, backlink)
    argv = build_issue_argv(target_repo, title, full_body, labels)
    return parse_issue_url(runner(argv))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="File a cross-repo issue (The Telegraph relay).")
    parser.add_argument("--repo", required=True, help="target repo slug")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", default="")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--source-repo", default=None, help="filing repo (from: label)")
    parser.add_argument("--backlink", default=None, help="originating issue URL")
    args = parser.parse_args(argv)
    try:
        url = file_cross_repo_issue(
            args.repo,
            args.title,
            args.body,
            label=args.label,
            source_repo=args.source_repo,
            backlink=args.backlink,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr or "gh issue create failed\n")
        return exc.returncode or 1
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
