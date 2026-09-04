# ABOUTME: Reads the diff, the issue, the tests, the doctrine and the gaudi report for a review.
# ABOUTME: Every probe answers None when it could not look, never an empty string that reads clean.

"""The outside world, as review-input assembly is allowed to touch it (OS#428).

One method per question, and every one of them returns ``None`` — never ``""``
— when the answer could not be obtained. That distinction is the whole contract:
`review_input` turns a ``None`` into an ``UNMEASURED`` section and exit 2, and an
empty string into a measured empty answer. Collapsing the two is the false green
this instrument exists to remove.

Stdlib only. `gh` is invoked through the REST API rather than `gh issue view`
because the GraphQL path 500s on Projects-classic in this org, which would make
every issue read a silent could-not-look.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from oversteward.gaudi_binary import gaudi_binary

_GIT = "git"
_GH = "gh"
_HEAD = "HEAD"
_DIFF = "diff"

#: Distinguishes "work out where gaudi is" from "there is no gaudi" — the
#: second must be expressible, or the could-not-look branch cannot be tested.
_AUTODETECT = object()


def _run(args: list[str], cwd: Path) -> str | None:
    """Stdout of a successful command, or None. Never raises, never returns ''."""
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell, no untrusted words
            args, cwd=str(cwd), capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


class ShellCollector:
    """Answers the assembler's questions from one checkout, via git / gh / gaudi."""

    def __init__(self, root: Path, *, gaudi: Path | None | object = _AUTODETECT) -> None:
        self._root = root
        # `gaudi=None` means "there is none" — a caller must be able to say
        # that, or the absent-gaudi branch is unreachable from a test and the
        # COULD-NOT-LOOK path ships unproven.
        self._gaudi = gaudi_binary() if gaudi is _AUTODETECT else gaudi

    def _merge_base(self, base: str) -> str | None:
        out = _run([_GIT, "merge-base", base, _HEAD], self._root)
        return out.strip() if out else None

    def merge_base(self, base: str) -> str | None:
        """The commit the branch forked from ``base``, recorded on every ledger line."""
        return self._merge_base(base)

    def branch(self) -> str | None:
        """The checked-out branch — the round count belongs to it."""
        out = _run([_GIT, "rev-parse", "--abbrev-ref", _HEAD], self._root)
        return out.strip() if out else None

    def diff(self, base: str) -> str | None:
        """The branch's own changes — merge-base, so base-branch commits are excluded."""
        point = self._merge_base(base)
        if point is None:
            return None
        return _run([_GIT, _DIFF, "--no-color", point, _HEAD], self._root)

    def changed_files(self, base: str) -> list[str] | None:
        point = self._merge_base(base)
        if point is None:
            return None
        out = _run([_GIT, _DIFF, "--name-only", point, _HEAD], self._root)
        if out is None:
            return None
        return [line for line in out.splitlines() if line.strip()]

    def deleted_files(self, base: str) -> list[str] | None:
        """The paths this branch removed, or None when that could not be established.

        An empty list means "the branch deleted nothing" and None means "the
        question could not be answered" — the assembler needs both, because a
        file it cannot read is reviewable material when it was deleted and an
        unmeasured input when nobody can say.
        """
        point = self._merge_base(base)
        if point is None:
            return None
        out = _run([_GIT, _DIFF, "--diff-filter=D", "--name-only", point, _HEAD], self._root)
        if out is None:
            return None
        return [line for line in out.splitlines() if line.strip()]

    def file_text_at_base(self, base: str, relpath: str) -> str | None:
        """A file's content at the merge base — the only place a deleted file still exists."""
        point = self._merge_base(base)
        if point is None:
            return None
        return _run([_GIT, "show", f"{point}:{relpath}"], self._root)

    def issue_body(self, repo: str, number: int) -> str | None:
        out = _run([_GH, "api", f"repos/{repo}/issues/{number}"], self._root)
        if out is None:
            return None
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            return None
        title = payload.get("title")
        body = payload.get("body")
        if title is None:
            return None
        return f"{title}\n\n{body or '(the issue has an empty body)'}"

    def file_text(self, relpath: str) -> str | None:
        path = self._root / relpath
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            # None means only "not in the working tree". Whether that is a
            # deletion (reviewable — read it at the base) or a blind spot is
            # `deleted_files`' question, never this one's.
            return None

    def claude_md(self) -> str | None:
        try:
            return (self._root / "CLAUDE.md").read_text(encoding="utf-8")
        except OSError:
            return None

    def gaudi_json(self, relpaths: list[str]) -> str | None:
        """One `gaudi check --severity warn --format json` per file, merged.

        Per file because `gaudi check` takes a single positional path and exits
        0 while rejecting a second one on stderr — a multi-path invocation would
        return success having read nothing (`pr-workflow.md`: rc=0 is not a pass
        on its own).
        """
        if self._gaudi is None:
            return None
        reports: dict[str, object] = {}
        for relpath in relpaths:
            out = _run(
                [
                    str(self._gaudi),
                    "check",
                    "--severity",
                    "warn",
                    "--format",
                    "json",
                    "--no-exit-code",
                    relpath,
                ],
                self._root,
            )
            if out is None:
                return None
            try:
                reports[relpath] = json.loads(out)
            except json.JSONDecodeError:
                return None
        return json.dumps(reports, indent=2, sort_keys=True)
