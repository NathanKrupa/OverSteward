# ABOUTME: Stop-the-line rule — whether an open ci-red or dispatch-paused issue refuses a dispatch.
# ABOUTME: Pure MIDDLE service: IntakeIssues and comment text in, Allowed or Stopped(reasons) out.

"""Decide whether the line is stopped for one dispatch target (OS#657).

* An open ``dispatch-paused`` issue stops every dispatch on the repository —
  the ci-red issue and its fixes included. Only removing the label resumes.
* An open ``ci-red`` issue stops every dispatch but two: the ``ci-red`` issue
  itself, and an issue whose body or comments declare a fix of it —
  ``closes``, ``fixes`` or ``resolves`` followed by ``#<m>``, where ``#<m>`` is
  an *open* ``ci-red`` issue in the same repository. Naming any other issue is
  not a pass, and neither is a bare mention.

The rule fails closed: anything not shown to be the fix is refused.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from oversteward.intake.labels import CI_RED, DISPATCH_PAUSED
from oversteward.intake.models import IntakeIssue

#: An override comment opens with one of these; the ci-red sweep counts them per issue.
LINE_OVERRIDE_PREFIX = "LINE OVERRIDE:"
#: Written by the stdlib hook ``guard_promote_ci_red.py``, which cannot import this module;
#: ``tests/ci_red/test_ci_red.py`` pins its ``OVERRIDE_COMMENT`` to this prefix.
PROMOTE_OVERRIDE_PREFIX = "PROMOTE OVERRIDE:"

#: A same-repo fix declaration. ``owner/repo#n`` does not match: the ``#`` must follow whitespace.
_FIX = re.compile(r"\b(?:closes|fixes|resolves)\s+#(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Allowed:
    reason: str


@dataclass(frozen=True, slots=True)
class Stopped:
    reasons: tuple[str, ...]
    #: The open ci-red issue numbers; an override records itself on each.
    ci_red: tuple[int, ...]
    #: True when only ci-red issues stop the line, so an override may lift it.
    overridable: bool


def declared_fixes(texts: Iterable[str]) -> frozenset[int]:
    """Every issue number the texts declare a fix of."""
    return frozenset(int(m.group(1)) for text in texts for m in _FIX.finditer(text))


def _named(issue: IntakeIssue, label: str) -> str:
    return f"{issue.repo}#{issue.number} has `{label}` — {issue.title}"


def stop_line(
    target: IntakeIssue, repo_issues: Iterable[IntakeIssue], comments: Iterable[str] = ()
) -> Allowed | Stopped:
    """Whether ``target`` may dispatch, given every open issue in its repository."""
    issues = tuple(repo_issues)
    paused = [i for i in issues if DISPATCH_PAUSED in i.labels]
    red = [i for i in issues if CI_RED in i.labels]
    red_numbers = tuple(sorted(i.number for i in red))
    if paused:
        reasons = [_named(i, DISPATCH_PAUSED) for i in paused] + [_named(i, CI_RED) for i in red]
        return Stopped(tuple(reasons), red_numbers, overridable=False)
    if not red:
        return Allowed(f"{target.repo}: 0 open ci-red or dispatch-paused issues")
    if CI_RED in target.labels:
        return Allowed(f"{target.repo}#{target.number} is itself a ci-red issue")
    fixed = declared_fixes((target.body, *comments)) & {i.number for i in red}
    if fixed:
        names = ", ".join(f"#{n}" for n in sorted(fixed))
        return Allowed(f"{target.repo}#{target.number} declares the fix of ci-red {names}")
    return Stopped(tuple(_named(i, CI_RED) for i in red), red_numbers, overridable=True)
