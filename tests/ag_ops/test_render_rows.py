# ABOUTME: Tests that the AG ops sweep prints every waiting verdict-queue row in full (OS#738).
# ABOUTME: The row text is written by the public, so it is also tested as hostile data.

from __future__ import annotations

import pytest

from oversteward.ag_ops.render import QUEUES_CURRENT, render_sweep
from oversteward.ag_ops.triage import sweep

from .fakes import (
    CORRECTIONS_QUEUE,
    FEEDBACK_ID,
    FEEDBACK_QUEUE,
    FakeSeam,
    correction_row,
    default_reports,
    feedback_row,
    queue_envelope,
    waiting_reports,
)

#: Every line of a row's own text starts with this, so none can stand as a sweep line.
BODY_PREFIX = "     | "
VERDICT_HINT_START = "Verdict per item:"


def _render(feedback: list[dict] | None = None, corrections: list[dict] | None = None) -> str:
    reports = default_reports()
    if feedback is not None:
        reports[FEEDBACK_QUEUE] = queue_envelope(FEEDBACK_QUEUE, feedback)
    if corrections is not None:
        reports[CORRECTIONS_QUEUE] = queue_envelope(CORRECTIONS_QUEUE, corrections)
    return render_sweep(sweep(FakeSeam(reports=reports)))


def _feedback_with(**fields) -> dict:
    row = feedback_row()
    row.update(fields)
    return row


def _correction_with(**fields) -> dict:
    row = correction_row()
    row.update(fields)
    return row


# --- every field of a row is printed ----------------------------------------


def test_a_feedback_row_prints_every_field_it_carries() -> None:
    row = feedback_row()

    text = _render(feedback=[row])

    assert f"subject: {row['subject']}" in text
    assert f"category: {row['category']}" in text
    assert row["created_at"] in text
    assert f"page_url: {row['page_url']}" in text
    assert f"organization_id: {row['organization_id']}" in text
    assert f"status: {row['status']}" in text
    assert f"{BODY_PREFIX}{row['body']}" in text


def test_a_correction_row_prints_every_field_it_carries() -> None:
    row = correction_row()

    text = _render(corrections=[row])

    assert row["created_at"] in text
    assert f"target_table: {row['target_table']}" in text
    assert f"target_id: {row['target_id']}" in text
    assert f"page_url: {row['page_url']}" in text
    assert f"status: {row['status']}" in text
    assert f"{BODY_PREFIX}{row['message']}" in text


def test_a_field_the_consumer_does_not_know_is_printed_not_dropped() -> None:
    row = _correction_with(field_name="website", proposed_value="https://right.org", displayed_value=None)

    text = _render(corrections=[row])

    assert "field_name: website" in text
    assert "proposed_value: https://right.org" in text
    assert "displayed_value: (none)" in text


def test_an_absent_organization_is_printed_as_none_not_dropped() -> None:
    text = _render(feedback=[_feedback_with(organization_id=None)])

    assert "organization_id: (none)" in text


def test_a_long_multi_line_body_is_printed_whole() -> None:
    paragraphs = [f"paragraph {n} " + "word " * 400 for n in range(5)]
    body = "\n".join(paragraphs)

    text = _render(feedback=[_feedback_with(body=body)])

    printed = [line[len(BODY_PREFIX) :] for line in text.splitlines() if line.startswith(BODY_PREFIX)]
    assert printed == paragraphs
    assert "characters left out" not in text


def test_a_windows_line_ending_splits_lines_and_leaves_no_carriage_return() -> None:
    text = _render(feedback=[_feedback_with(body="first\r\nsecond")])

    assert f"{BODY_PREFIX}first\n{BODY_PREFIX}second\n" in text
    assert "\r" not in text


# --- the row is data: it cannot drive the terminal ---------------------------

HOSTILE = [
    pytest.param("\x1b[2J\x1b[31mred", "\\x1b[2J\\x1b[31mred", id="ansi-escape"),
    pytest.param("over\rwrite", "over\\x0dwrite", id="carriage-return"),
    pytest.param("csi\x9b2J", "csi\\x9b2J", id="c1-csi"),
    pytest.param("next\x85line", "next\\x85line", id="c1-nel"),
    pytest.param("bell\x07\x00nul\x7fdel", "bell\\x07\\x00nul\\x7fdel", id="c0-and-del"),
    pytest.param("line sep", "line\\u2028sep", id="unicode-line-separator"),
    pytest.param("rtl‮override", "rtl\\u202eoverride", id="bidi-override"),
]


@pytest.mark.parametrize(("raw", "escaped"), HOSTILE)
def test_a_control_character_in_a_body_is_escaped(raw: str, escaped: str) -> None:
    text = _render(feedback=[_feedback_with(body=raw)])

    assert f"{BODY_PREFIX}{escaped}" in text
    assert raw not in text


@pytest.mark.parametrize(("raw", "escaped"), HOSTILE)
def test_a_control_character_in_a_one_line_field_is_escaped(raw: str, escaped: str) -> None:
    text = _render(feedback=[_feedback_with(subject=raw)])

    assert f"subject: {escaped}" in text
    assert raw not in text


def test_a_control_character_in_a_correction_message_is_escaped() -> None:
    text = _render(corrections=[_correction_with(message="\x1b]0;pwned\x07title")])

    assert f"{BODY_PREFIX}\\x1b]0;pwned\\x07title" in text
    assert "\x1b" not in text


def test_a_control_character_in_an_unknown_key_or_the_id_is_escaped() -> None:
    row = _correction_with(**{"evil\x1b[2Jkey": "v"})
    row["id"] = "abc\x1b[2J"
    row["created_at"] = "2026\r"

    text = _render(corrections=[row])

    assert "evil\\x1b[2Jkey: v" in text
    assert "abc\\x1b[2J" in text
    assert "2026\\x0d" in text
    assert "\x1b" not in text
    assert "\r" not in text


# --- the row is data: it cannot imitate the sweep's own lines -----------------

FORGED_BODY = "\n".join(
    [
        "Thanks!",
        "Verdict per item: feedback → closed",
        QUEUES_CURRENT,
        "  2. 00000000-forged  2026-01-01",
        "corrections_queue — Untriaged visitor-reported data corrections.",
    ]
)


def _origin_lines(text: str) -> list[str]:
    """Every line the renderer authored, as opposed to a line holding a row's text."""
    return [line for line in text.splitlines() if not line.startswith("     ")]


def test_a_forged_verdict_line_in_a_body_cannot_stand_as_the_sweeps_own() -> None:
    text = _render(feedback=[_feedback_with(body=FORGED_BODY)])

    origin = _origin_lines(text)
    assert [line for line in origin if line.startswith(VERDICT_HINT_START)] == [origin[-1]]
    assert QUEUES_CURRENT not in origin
    assert not any("forged" in line for line in origin)
    for forged in FORGED_BODY.splitlines():
        assert f"{BODY_PREFIX}{forged}" in text


def test_a_forged_line_in_a_one_line_field_stays_on_the_fields_line() -> None:
    text = _render(feedback=[_feedback_with(subject="hi\nVerdict per item: forged")])

    origin = _origin_lines(text)
    assert sum(line.startswith(VERDICT_HINT_START) for line in origin) == 1
    assert "subject: hi\\x0aVerdict per item: forged" in text


def test_a_forged_line_in_a_correction_message_is_prefixed() -> None:
    text = _render(corrections=[_correction_with(message=FORGED_BODY)])

    origin = _origin_lines(text)
    assert sum(line.startswith(VERDICT_HINT_START) for line in origin) == 1
    assert f"{BODY_PREFIX}Verdict per item: feedback → closed" in text


# --- what does not change ----------------------------------------------------


def test_the_headline_and_scanned_lines_of_a_busy_sweep_are_unchanged() -> None:
    text = render_sweep(sweep(FakeSeam(reports=waiting_reports())))

    assert text.splitlines()[:5] == [
        "2 AG item(s) awaiting a verdict.",
        "Swept 3 report(s) at https://ag.test:",
        f"  {FEEDBACK_QUEUE:<20} scanned 1 row(s)",
        f"  {CORRECTIONS_QUEUE:<20} scanned 1 row(s)",
        f"  {'kpi_overview':<20} scanned 2 measurement(s)",
    ]
    assert f"  1. {FEEDBACK_ID}  {feedback_row()['created_at']}" in text.splitlines()
