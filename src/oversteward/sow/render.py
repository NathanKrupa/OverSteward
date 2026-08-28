# ABOUTME: Text only — renders the plan for the operator and the per-context report for the PR body.
# ABOUTME: No decisions and no I/O; the same lines serve the dry run, the commit message and the PR.

from __future__ import annotations

from .plan import (
    DEPLOYED,
    DIVERGED,
    IDENTICAL,
    NOT_ADOPTED,
    UNREADABLE,
    ContextPlan,
    SowPlan,
    SowReport,
)

_MERGE_HINT = "gh pr merge {url} --merge  # sow never merges; review first"


def _is_unreadable(ctx: ContextPlan) -> bool:
    blocking = ctx.blocking_gate
    return blocking is not None and blocking.verdict == UNREADABLE


def _gate_line(ctx: ContextPlan) -> str:
    return "  gates: " + " · ".join(f"{gate.gate} {gate.verdict}" for gate in ctx.gates)


def _member_lines(ctx: ContextPlan) -> list[str]:
    if not ctx.members:
        return []
    width = max(len(member.member) for member in ctx.members)
    marks = {
        DIVERGED: "!  flagged — edited downstream, never overwritten",
        NOT_ADOPTED: "   not adopted here — left alone",
    }
    lines = []
    for member in sorted(ctx.members, key=lambda m: m.member):
        note = marks.get(member.status, "" if member.status == IDENTICAL else "→  deploy")
        lines.append(f"  {member.member:<{width}}  {member.status:<18} {note}".rstrip())
    return lines


def render_context_report(ctx: ContextPlan, date: str) -> str:
    """The per-context report: PR body, commit message body, and dry-run detail."""
    lines = [
        f"# oversteward sync — {ctx.context_id} — {date}",
        "",
        f"Canonical `shared/scripts/dev/` deployed from OverSteward onto `{ctx.branch}`.",
        "",
        "## Deployed",
    ]
    lines.extend(
        f"- `{member.relpath}` — {member.status} "
        f"({(member.deployed_blob or 'absent')[:7]} → {member.canonical_blob[:7]})"
        for member in ctx.deployable
    )
    if not ctx.deployable:
        lines.append("- nothing")
    if ctx.diverged:
        lines += [
            "",
            "## Flagged, not written",
            "",
            "These copies match no blob canon has ever carried, so they were edited",
            "downstream. sow never overwrites one — promote it upstream or restore it",
            "deliberately.",
            "",
        ]
        lines.extend(f"- `{member.relpath}`" for member in ctx.diverged)
    lines += ["", "## Gates", ""]
    lines.extend(f"- {gate.gate} {gate.verdict} — {gate.detail}" for gate in ctx.gates)
    return "\n".join(lines) + "\n"


def render_plan(plan: SowPlan) -> str:
    """The operator-facing plan. Names the count it checked, always."""
    mode = "apply" if plan.apply_requested else "dry run"
    lines = [
        f"sow — {plan.date} ({mode})",
        f"checked {plan.members_checked} canonical members across "
        f"{len(plan.contexts)} context(s)",
    ]
    for ctx in plan.contexts:
        where = f"origin/{ctx.branch} → {ctx.sync_branch}" if ctx.branch else "not registered"
        lines += ["", f"## {ctx.context_id} ({where})", _gate_line(ctx)]
        blocking = ctx.blocking_gate
        if blocking is not None:
            lines.append(f"  {blocking.gate} {blocking.verdict}: {blocking.detail}")
        lines.extend(_member_lines(ctx))
    if plan.without_checkout:
        lines += ["", f"not checked out locally: {', '.join(plan.without_checkout)}"]
    unmeasured = [ctx.context_id for ctx in plan.contexts if _is_unreadable(ctx)]
    if unmeasured:
        lines += ["", f"NOT MEASURED — {', '.join(unmeasured)} could not be read"]
    elif not any(ctx.deployable for ctx in plan.contexts):
        lines += ["", "nothing to do — every checked member is identical, flagged, or not adopted"]
    return "\n".join(lines) + "\n"


def render_report(report: SowReport) -> str:
    """What the run actually did, one line per context plus the merge commands."""
    lines = [
        f"sow — {report.date} ({'applied' if report.applied else 'dry run'})",
        f"checked {report.members_checked} canonical members across "
        f"{report.contexts_checked} context(s)",
        "",
    ]
    for outcome in report.outcomes:
        members = f" [{', '.join(outcome.members)}]" if outcome.members else ""
        lines.append(f"- {outcome.context_id}: {outcome.action}{members} — {outcome.detail}")
    urls = [outcome.pr_url for outcome in report.outcomes if outcome.pr_url]
    if urls:
        lines += ["", "Review, then merge each yourself:"]
        lines.extend(f"  {_MERGE_HINT.format(url=url)}" for url in urls)
    if not any(outcome.action == DEPLOYED for outcome in report.outcomes):
        lines += ["", "nothing was written"]
    if report.without_checkout:
        lines += ["", f"not checked out locally: {', '.join(report.without_checkout)}"]
    return "\n".join(lines) + "\n"
