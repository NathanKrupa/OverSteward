# ABOUTME: Renders the liveness report for the terminal — findings first, then the tally.
# ABOUTME: A clean estate says how many services it actually checked, never just "ok".

"""Format a :class:`LivenessReport`.

A clean result prints the count it checked. "All 20 services running" is a
measurement; "ok" is a claim, and the two read identically when the instrument
is broken — which is the confusion this whole sweep exists to end.
"""

from __future__ import annotations

from collections import Counter

from oversteward.liveness.models import Health, LivenessReport


def render(report: LivenessReport) -> str:
    tally = Counter(state.health for state in report.states)
    checked = len(report.states)
    summary = (
        f"{tally[Health.RUNNING]} running · {tally[Health.COMPLETED]} completed · "
        f"{tally[Health.IN_FLIGHT]} in-flight · {tally[Health.DOWN]} down · "
        f"{tally[Health.UNKNOWN]} unknown"
    )

    findings = report.findings
    if not findings:
        return f"All {checked} service(s) accounted for — {summary}."

    lines = [
        f"{len(findings)} service(s) need attention ({checked} checked — {summary}):",
        "",
    ]
    for state in findings:
        lines.append(
            f"  {state.project}/{state.name}  {state.health.value.upper()}  "
            f"(status={state.status or '<none>'}, stopped={state.stopped})"
        )
    return "\n".join(lines)


__all__ = ["render"]
