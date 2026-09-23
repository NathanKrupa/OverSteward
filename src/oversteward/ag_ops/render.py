# ABOUTME: Text rendering for the AG ops sweep and record steps — formatting only.
# ABOUTME: The clean-sweep line always names its scanned counts; see triage.py's docstring.

"""How a sweep reads.

The clean case is the one worth guarding: a drained seam prints a per-report
``scanned`` count, never a bare "ok". "Nothing is waiting" is a measurement and
has to show its working, or it is indistinguishable from a sweep that never
asked — which is the exact false green the estate keeps paying for.
"""

from __future__ import annotations

from .triage import RecordResult, ReportResult, SweepResult

#: The headline a drained seam prints. It is followed, always, by the counts.
QUEUES_CURRENT = "AG ops queues current — nothing awaiting a verdict."

_QUEUE_ROW_FIELDS = ("subject", "field_name", "category")
#: What names a measurement row — ``asdict(apps.ops.services.Alert)``'s fields.
_MEASUREMENT_ROW_FIELDS = ("type", "message", "count")
_LABEL_JOIN = " · "
_VERDICT_HINT = "Verdict per item: feedback → responded | closed;  correction → reviewed | rejected"


def render_sweep(result: SweepResult) -> str:
    """The sweep report: the queues if any are waiting, and the counts either way."""
    head = (
        QUEUES_CURRENT
        if result.is_clean
        else f"{result.total_waiting} AG item(s) awaiting a verdict."
    )
    lines = [head, f"Swept {len(result.reports)} report(s) at {result.base_url}:"]
    lines.extend(_render_scanned(report) for report in result.reports)
    lines.extend(_render_measurements(result))
    lines.extend(_render_queues(result))
    return "\n".join(lines) + "\n"


def _render_scanned(report: ReportResult) -> str:
    """One report's measurement line — what it looked at, and whether it saw all of it."""
    shape = "row(s)" if report.is_queue else "measurement(s)"
    completeness = "" if report.complete else " (PAGE CAPPED — more remain)"
    return f"  {report.name:<20} scanned {report.scanned} {shape}{completeness}"


def _render_measurements(result: SweepResult) -> list[str]:
    """Every row-list measurement's rows — shown whether or not anything is waiting."""
    lines = []
    for report in result.reports:
        if report.measurements:
            lines.append("")
            lines.append(f"{report.name} — {report.description}")
            lines.extend(
                f"{index:>3}. {_measurement_label(row)}" for index, row in enumerate(report.measurements, 1)
            )
    return lines


def _measurement_label(row) -> str:
    """``type · message · count``, or the row itself when it carries none of them."""
    if not isinstance(row, dict):
        return str(row)
    parts = [str(row[field]) for field in _MEASUREMENT_ROW_FIELDS if row.get(field) not in (None, "")]
    return _LABEL_JOIN.join(parts) or str(row)


def _render_queues(result: SweepResult) -> list[str]:
    """The waiting rows themselves, one block per non-empty queue."""
    if result.is_clean:
        return []
    lines = []
    for report in result.reports:
        if report.waiting:
            lines.append("")
            lines.append(f"{report.name} — {report.description}")
            lines.extend(_render_row(index, row) for index, row in enumerate(report.items or (), 1))
    lines.append("")
    lines.append(_VERDICT_HINT)
    return lines


def _render_row(index: int, row: dict) -> str:
    """One queue row: its id, when it arrived, and whatever names it."""
    head = f"{index:>3}. {row.get('id', '?')}  {row.get('created_at', 'unknown')}"
    label = _row_label(row)
    return f"{head}\n     {label}" if label else head


def _row_label(row: dict) -> str:
    """The most human field this row carries, whichever queue it came from."""
    parts = [str(row[field]) for field in _QUEUE_ROW_FIELDS if row.get(field)]
    return _LABEL_JOIN.join(parts)


def render_record(result: RecordResult) -> str:
    """Every per-item answer, then the counts. A refusal is printed, never summarised away."""
    lines = [_render_result(item) for item in result.results]
    lines.append(f"recorded {result.recorded}, failed {result.failed}")
    return "\n".join(lines) + "\n"


def _render_result(item: dict) -> str:
    """One item's answer: what was asked, what happened, and why when it did not."""
    asked = f"{item.get('kind', '?')} {item.get('id', '?')} → {item.get('requested_status', '?')}"
    if item.get("ok"):
        return f"  ok       {asked}  (now {item.get('status', '?')})"
    return f"  REFUSED  {asked}  [{item.get('outcome', '?')}] {item.get('detail', '')}".rstrip()
