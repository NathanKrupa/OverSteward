# ABOUTME: Tests for the Sentry triage service — ledger round-trip, sweep diff, and record.
# ABOUTME: Everything runs against the fake connector and tmp_path; no live Sentry, no token.

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from oversteward.sentry.client import SentryUnavailableError
from oversteward.sentry.render import LEDGER_CURRENT, render_record, render_sweep
from oversteward.sentry.triage import (
    LedgerEntry,
    TriageError,
    TriageStore,
    record,
    sweep,
)

from .fakes import (
    AG,
    AG_1,
    AG_2,
    FIRST_SEEN,
    GS,
    GS_9,
    blind_sentry,
    empty_sentry,
    issue,
    two_project_sentry,
)

WHEN = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
FIXED = "fixed"
FILED = "filed"
NOISE = "noise-resolved"
REF = "AG#1500"
GS_REF = "GS#2166"


@pytest.fixture
def store(tmp_path: Path) -> TriageStore:
    return TriageStore(
        ledger_path=tmp_path / "sentry" / "ledger.jsonl",
        pending_path=tmp_path / "sentry" / "pending.json",
    )


@pytest.fixture
def swept(store: TriageStore) -> TriageStore:
    """A store whose pending snapshot holds all three issues, none ruled on."""
    store.save_pending(sweep(two_project_sentry(), store).new_issues)
    return store


# --- ledger -----------------------------------------------------------------


def test_missing_ledger_reads_empty(store: TriageStore) -> None:
    assert store.recorded() == {}


def test_append_then_read_round_trips_every_field(store: TriageStore) -> None:
    entry = LedgerEntry(
        short_id=GS_9,
        issue_id="python9",
        project=GS,
        title="boom",
        first_seen=FIRST_SEEN,
        verdict=FILED,
        ref=GS_REF,
        recorded_at=WHEN.isoformat(),
    )

    store.append(entry)

    assert store.recorded() == {GS_9: entry}


def test_later_line_supersedes_an_earlier_verdict(swept: TriageStore) -> None:
    record(swept, GS_9, FILED, GS_REF, WHEN)

    record(swept, GS_9, FIXED, "GS#2170", WHEN)

    assert swept.recorded()[GS_9].verdict == FIXED


def test_a_damaged_ledger_line_is_skipped_not_fatal(store: TriageStore) -> None:
    store.ledger_path.parent.mkdir(parents=True)
    store.ledger_path.write_text('{"broken\n{"shortId": "PYTHON-9", "verdict": "fixed"}\n')

    assert list(store.recorded()) == [GS_9]


# --- sweep ------------------------------------------------------------------


def test_sweep_enumerates_projects_rather_than_assuming_slugs(store: TriageStore) -> None:
    assert sweep(two_project_sentry(), store).projects == (AG, GS)


def test_sweep_returns_every_unresolved_issue_when_the_ledger_is_empty(store: TriageStore) -> None:
    result = sweep(two_project_sentry(), store)

    assert [i.short_id for i in result.new_issues] == [AG_1, AG_2, GS_9]


def test_sweep_subtracts_issues_that_already_have_a_verdict(swept: TriageStore) -> None:
    record(swept, AG_1, FILED, "AG#1", WHEN)

    result = sweep(two_project_sentry(), swept)

    assert [i.short_id for i in result.new_issues] == [AG_2, GS_9]
    assert result.unresolved_count == 3
    assert result.recorded_count == 1


def test_a_fully_ruled_ledger_sweeps_current(swept: TriageStore) -> None:
    for short_id in (AG_1, AG_2, GS_9):
        record(swept, short_id, NOISE, "known", WHEN)

    result = sweep(two_project_sentry(), swept)

    assert result.is_current
    assert result.new_issues == ()


def test_sweeping_twice_on_a_drained_ledger_is_idempotent(store: TriageStore) -> None:
    empty = empty_sentry()

    first = render_sweep(sweep(empty, store))
    second = render_sweep(sweep(empty, store))

    assert first == second
    assert LEDGER_CURRENT in second


def test_sweep_raises_rather_than_reporting_an_empty_queue_when_it_cannot_look(
    store: TriageStore,
) -> None:
    with pytest.raises(SentryUnavailableError):
        sweep(blind_sentry(), store)


# --- record -----------------------------------------------------------------


def test_record_uses_the_pending_snapshot_so_no_network_is_needed(store: TriageStore) -> None:
    store.save_pending([issue(AG_1)])

    entry = record(store, AG_1, FIXED, REF, WHEN)

    assert entry.project == AG
    assert entry.title == f"{AG_1} blew up"
    assert entry.first_seen == FIRST_SEEN
    assert entry.recorded_at == WHEN.isoformat()


def test_record_rejects_a_verdict_outside_the_vocabulary(swept: TriageStore) -> None:
    with pytest.raises(TriageError, match="unknown verdict"):
        record(swept, AG_1, "later", "", WHEN)


def test_record_refuses_a_short_id_the_last_sweep_never_offered(store: TriageStore) -> None:
    with pytest.raises(TriageError, match="not in the last sweep"):
        record(store, "AIGRANTHELPER-404", FIXED, "", WHEN)


def test_a_recorded_issue_does_not_come_back_in_the_next_sweep(swept: TriageStore) -> None:
    record(swept, GS_9, FIXED, GS_REF, WHEN)

    assert GS_9 not in {i.short_id for i in sweep(two_project_sentry(), swept).new_issues}


# --- rendering --------------------------------------------------------------


def test_the_clean_line_and_the_queue_report_never_read_alike(store: TriageStore) -> None:
    current = render_sweep(sweep(empty_sentry(), store))
    queued = render_sweep(sweep(two_project_sentry(), store))

    assert LEDGER_CURRENT in current
    assert LEDGER_CURRENT not in queued
    assert "awaiting a verdict" in queued


def test_the_queue_report_names_each_issue_and_its_project(store: TriageStore) -> None:
    rendered = render_sweep(sweep(two_project_sentry(), store))

    assert f"{GS_9}  [{GS}]" in rendered
    assert "3 Sentry issue(s) awaiting a verdict" in rendered


def test_render_record_states_the_verdict_and_its_reference(store: TriageStore) -> None:
    store.save_pending([issue(AG_1)])

    line = render_record(record(store, AG_1, FILED, REF, WHEN))

    assert AG_1 in line
    assert FILED in line
    assert REF in line
