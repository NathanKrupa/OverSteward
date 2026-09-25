# ABOUTME: Text rendering for the /stage-health sweep and record steps — formatting only.
# ABOUTME: Every outcome names its count and its route; "ledger current" is unreachable from no_rows.

from __future__ import annotations

from .triage import TRACKING_VERDICTS, HealthDocument, Ruling, SweepResult

#: The line a sweep with every RED row ruled on prints.
LEDGER_CURRENT = "Stage-health ledger current — every RED row ruled on."
VERDICT_HINT = (
    "Verdict for each: stage_health.py record <row> fixed | filed --ref GS#<n> | known --ref GS#<n>"
)


def _canary_phrase(document: HealthDocument) -> str:
    """The canaries' state for the headline; ``RED`` unless every expected canary ran and passed.

    Missing canary rows, a failed count that was not reported, an evaluated
    count that differs from the expected one, and any failure each read RED,
    so canaries that did not run or did not pass never headline as a pass.
    """
    if not document.canaries_configured:
        return "canaries not configured"
    expected = "?" if document.canaries_expected is None else document.canaries_expected
    evaluated = document.canaries_evaluated
    if evaluated is None:
        return f"canaries RED: no canary rows ({expected} expected)"
    counted = f"{evaluated} of {expected} evaluated"
    mismatch = evaluated != document.canaries_expected
    if mismatch:
        counted += " (evaluated ≠ expected)"
    failed = document.canaries_failed
    if failed is None:
        return f"canaries RED: {counted}, failed count not reported"
    state = "canaries RED" if mismatch or failed else "canaries"
    return f"{state}: {counted}, {failed} failed"


def scope_line(document: HealthDocument) -> str:
    """The count a result names: stages, days seen of the window, canaries."""
    return (
        f"{document.stage_count} stages, {document.day_count} of {document.window_days} days, "
        f"{_canary_phrase(document)}"
    )


def _window(document: HealthDocument) -> str:
    return f"{document.first_day}..{document.last_day}"


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _label(ruling: Ruling) -> str:
    if ruling.verdict in TRACKING_VERDICTS:
        return f"{ruling.verdict.upper()}→{ruling.ref}"
    return f"{ruling.verdict.upper()}@{ruling.ledger_day}"


def render_no_rows(document: HealthDocument) -> str:
    return (
        f"No stage_health rows in {_window(document)} (via: {document.via}): the "
        "stage_health_snapshot asset is not "
        f"running. That is a finding of its own, not a quiet window ({scope_line(document)})."
    )


def render_unreadable(document: HealthDocument) -> str:
    return (
        f"could not read stage health for {_window(document)} (via: {document.via}): "
        f"{document.error}"
    )


def _table(document: HealthDocument) -> list[str]:
    lines = [f"  {'stage':<20} {'metric':<28} {'latest':>12}"]
    lines += [f"  {m.stage:<20} {m.metric:<28} {_fmt(m.latest):>12}" for m in document.metrics]
    return lines


def _context(document: HealthDocument) -> list[str]:
    lines = [f"  {f.severity:<6} {f.key} — {f.message}" for f in document.findings
             if f.severity != "RED"]
    if document.not_evaluated_count:
        lines.append(
            f"  {document.not_evaluated_count} rule(s) not evaluated — "
            "the verdict cannot be GREEN while any rule could not run."
        )
    return lines


def render_sweep(result: SweepResult) -> str:
    """The measured report: headline with its count, the table, the ruled rows, the queue."""
    doc = result.document
    lines = [
        f"Stage health {doc.verdict} for {_window(doc)} (latest ledger day {doc.latest_day}, "
        f"via: {doc.via}): "
        f"{scope_line(doc)}.",
        "",
        *_table(doc),
        "",
        *_context(doc),
    ]
    if result.tracked:
        lines.append(f"Ruled on ({len(result.tracked)}):")
        lines += [f"  {_label(t.ruling)}  {t.finding.key} — {t.finding.message}"
                  for t in result.tracked]
    if not result.queue:
        lines.append(LEDGER_CURRENT)
        return "\n".join(lines) + "\n"
    lines.append(f"{len(result.queue)} RED row(s) awaiting a verdict:")
    for index, queued in enumerate(result.queue, 1):
        lines.append(f"{index:>3}. {queued.finding.key} — {queued.finding.message}")
        if queued.reason:
            lines.append(f"     {queued.reason}")
    lines.append(VERDICT_HINT)
    return "\n".join(lines) + "\n"


def render_record(ruling: Ruling) -> str:
    ref = f" → {ruling.ref}" if ruling.ref else ""
    return (
        f"Recorded {ruling.key} as {ruling.verdict}{ref} "
        f"(ledger day {ruling.ledger_day}, at {ruling.recorded_at})."
    )
