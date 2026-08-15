# ABOUTME: Text rendering for the Sentry triage sweep and record steps — formatting only.
# ABOUTME: The clean-sweep line is deliberately unlike any failure line; see triage.py's docstring.

from __future__ import annotations

from .triage import LedgerEntry, SweepResult

#: The one line a drained ledger prints. It must never be reachable from a
#: failed read — "I found nothing" and "I could not look" are different answers.
LEDGER_CURRENT = "Sentry ledger current — nothing to triage."


def render_sweep(result: SweepResult) -> str:
    """The sweep report: either the clean line, or the queue with its context."""
    scope = f"{result.unresolved_count} unresolved across {len(result.projects)} project(s)"
    if result.is_current:
        return f"{LEDGER_CURRENT}\n{scope}; {result.recorded_count} ruled on.\n"
    lines = [
        f"{len(result.new_issues)} Sentry issue(s) awaiting a verdict "
        f"({scope}; {result.recorded_count} ruled on).",
        "",
    ]
    lines.extend(_render_issue(index, issue) for index, issue in enumerate(result.new_issues, 1))
    lines.append("")
    lines.append("Verdict for each: fixed | filed | noise-resolved")
    return "\n".join(lines) + "\n"


def _render_issue(index: int, issue) -> str:
    head = f"{index:>3}. {issue.short_id}  [{issue.project}]  {issue.title}"
    detail = f"     first seen {issue.first_seen or 'unknown'} · {issue.count} event(s)"
    if issue.permalink:
        detail += f" · {issue.permalink}"
    return f"{head}\n{detail}"


def render_record(entry: LedgerEntry) -> str:
    """Confirmation of one recorded verdict."""
    ref = f" → {entry.ref}" if entry.ref else ""
    return f"Recorded {entry.short_id} as {entry.verdict}{ref} (at {entry.recorded_at})."
