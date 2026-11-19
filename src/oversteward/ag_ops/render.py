# ABOUTME: Text rendering for the AG ops sweep and record steps — formatting only.
# ABOUTME: The clean-sweep line always names its scanned counts; see triage.py's docstring.

"""How a sweep reads.

The clean case is the one worth guarding: a drained seam prints a per-report
``scanned`` count, never a bare "ok". "Nothing is waiting" is a measurement and
has to show its working, or it is indistinguishable from a sweep that never
asked — which is the exact false green the estate keeps paying for.
"""

from __future__ import annotations

import unicodedata

from .triage import ROW_ID_KEY, RecordResult, ReportResult, SweepResult

#: The headline a drained seam prints. It is followed, always, by the counts.
QUEUES_CURRENT = "AG ops queues current — nothing awaiting a verdict."

#: A queue row's fields, by where they print. The head line carries the id and
#: date; the leading fields print first when present; every other field follows
#: in the producer's order; the free text the submitter wrote prints last, whole.
_ROW_HEAD_FIELDS = (ROW_ID_KEY, "created_at")
_ROW_LEADING_FIELDS = ("subject", "category", "target_table", "target_id", "page_url", "organization_id")
_ROW_TEXT_FIELDS = ("body", "message")
_ROW_INDENT = "     "
#: Every line of a row's free text starts with this, so none can pass as a sweep line.
_TEXT_PREFIX = f"{_ROW_INDENT}| "
_NONE = "(none)"
#: Control characters (C0, DEL, C1), and the line and paragraph separators.
_ESCAPED_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})
#: Bidirectional embeddings, overrides and isolates (U+202A–U+202E, U+2066–U+2069).
_BIDI_CONTROLS = frozenset(chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))
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
    """One queue row in full: its id and date, every field it carries, then its text.

    Nothing the producer sends is dropped, so a field AG adds prints the day it
    ships. Every line after the head is indented under it, and the row's own
    text is prefixed line by line, so no line a submitter wrote can begin where
    the sweep's lines begin.
    """
    item_id = _one_line(row.get(ROW_ID_KEY, "?"))
    lines = [f"{index:>3}. {item_id}  {_one_line(row.get('created_at', 'unknown'))}"]
    lines.extend(
        f"{_ROW_INDENT}{_one_line(key)}: {_one_line(row[key])}" for key in _field_order(row)
    )
    for key in _ROW_TEXT_FIELDS:
        if key in row:
            lines.append(f"{_ROW_INDENT}{key}:")
            lines.extend(f"{_TEXT_PREFIX}{line}" for line in _text_lines(row[key]))
    return "\n".join(lines)


def _field_order(row: dict) -> list:
    """The row's one-line fields: the familiar ones first, then any other in the producer's order."""
    shown = (*_ROW_HEAD_FIELDS, *_ROW_TEXT_FIELDS)
    leading = [key for key in _ROW_LEADING_FIELDS if key in row]
    rest = [key for key in row if key not in shown and key not in leading]
    return leading + rest


def _one_line(value) -> str:
    """A field value as one line of inert text: every control character, newlines included, escaped."""
    return _escape(_NONE if value is None else str(value))


def _text_lines(value) -> list[str]:
    """A free-text field as its own lines, each escaped. Only a line feed (or CRLF) breaks a line."""
    if value is None:
        return [_NONE]
    text = str(value).replace("\r\n", "\n")
    return [_escape(line) for line in text.split("\n")]


def _escape(text: str) -> str:
    """Replace each character a terminal would act on with its visible ``\\xNN`` / ``\\uNNNN`` spelling.

    Covers every C0 and C1 control and DEL (Unicode category ``Cc``), the line
    and paragraph separators, and the bidirectional overrides and isolates that
    can make a line display other than it reads. A backslash is left as it is,
    so a submitter's literal ``\\x1b`` and an escaped ESC print alike — both are
    inert, which is the property this guards.
    """
    return "".join(_escaped_char(char) for char in text)


def _escaped_char(char: str) -> str:
    if unicodedata.category(char) not in _ESCAPED_CATEGORIES and char not in _BIDI_CONTROLS:
        return char
    code = ord(char)
    return f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}"


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
