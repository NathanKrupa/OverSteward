# ABOUTME: Tests for the correction pass's closing-row ledger: the re-check clock it feeds the worklist,
# ABOUTME: and the probe that tells a pass that ran from one that never closed. Temp files only.

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from oversteward.dream import correction
from oversteward.dream.consolidate import MemoryStore
from oversteward.dream.correction_ledger import CorrectionLedger, LedgerUnreadable

from tests.dream.test_correction import TODAY, _names, _note, _sources

LOCAL = timezone(timedelta(hours=-5))


def _at(days_ago: int) -> str:
    """An `at` stamp ``days_ago`` days before TODAY, at noon local time."""
    day = TODAY - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=LOCAL).isoformat()


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _run(run: str, days_ago: int, filenames: list[str], *, closed: bool = True) -> list[dict]:
    rows = [{"event": "opened", "run": run, "at": _at(days_ago)}]
    rows += [
        {"event": "verdict", "run": run, "filename": name, "verdict": "unverified", "searched": ["x"]}
        for name in filenames
    ]
    if closed:
        rows.append({"event": "closed", "run": run, "at": _at(days_ago), "checked": len(filenames)})
    return rows


# ---- the clock ----------------------------------------------------------------


def test_a_ledgered_check_moves_the_note_out_until_the_floor(tmp_path: Path) -> None:
    """29 days since a closed run's verdict is not due; 30 is. The note's own date is far older."""
    store = tmp_path / "memory"
    _note(store, "a_checked_29.md", last_reinforced="'2025-01-01'")
    _note(store, "b_checked_30.md", last_reinforced="'2025-01-01'")
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, [*_run("r29", 29, ["a_checked_29.md"]), *_run("r30", 30, ["b_checked_30.md"])])

    checked = CorrectionLedger(ledger).last_checked()
    result = correction.build_worklist(
        MemoryStore(store), _sources(), today=TODAY, checked=checked
    ).to_dict()

    assert _names(result) == ["b_checked_30.md"]
    assert result["worklist"][0]["effective_date"] == _at(30)[:10]


def test_a_verdict_in_an_unclosed_run_starts_no_clock(tmp_path: Path) -> None:
    store = tmp_path / "memory"
    _note(store, "a_note.md", last_reinforced="'2025-01-01'")
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, _run("r1", 1, ["a_note.md"], closed=False))

    checked = CorrectionLedger(ledger).last_checked()
    result = correction.build_worklist(
        MemoryStore(store), _sources(), today=TODAY, checked=checked
    ).to_dict()

    assert checked == {}
    assert _names(result) == ["a_note.md"]


@pytest.mark.parametrize("order", ["oldest-first", "newest-first"])
def test_the_latest_closed_run_sets_the_clock(tmp_path: Path, order: str) -> None:
    """The live ledger is append-only, so oldest first; the latest day wins in either order."""
    ledger = tmp_path / "corrections.jsonl"
    runs = [_run("old", 40, ["a.md"]), _run("new", 3, ["a.md"])]
    if order == "newest-first":
        runs.reverse()
    _write_rows(ledger, [row for run in runs for row in run])

    assert CorrectionLedger(ledger).last_checked() == {"a.md": TODAY - timedelta(days=3)}


def test_an_absent_ledger_is_an_empty_clock(tmp_path: Path) -> None:
    assert CorrectionLedger(tmp_path / "absent.jsonl").last_checked() == {}


# ---- the probe ----------------------------------------------------------------


def test_probe_of_an_absent_ledger_is_never_run_and_stale(tmp_path: Path) -> None:
    probe = CorrectionLedger(tmp_path / "absent.jsonl").probe(today=TODAY).to_dict()

    assert probe == {
        "never_run": True,
        "stale": True,
        "last_closed": None,
        "days_since": None,
        "unclosed": 0,
    }


def test_probe_of_a_run_closed_today_is_not_stale(tmp_path: Path) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, _run("r1", 0, ["a.md"]))

    probe = CorrectionLedger(ledger).probe(today=TODAY).to_dict()

    assert probe["never_run"] is False
    assert probe["stale"] is False
    assert probe["days_since"] == 0
    assert probe["last_closed"]["run"] == "r1"
    assert probe["unclosed"] == 0


def test_probe_reports_the_latest_closing_row(tmp_path: Path) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, [*_run("old", 40, ["a.md"]), *_run("new", 0, ["b.md"])])

    probe = CorrectionLedger(ledger).probe(today=TODAY)

    assert probe.last_closed["run"] == "new"
    assert (probe.days_since, probe.stale) == (0, False)


@pytest.mark.parametrize(("days_ago", "stale"), [(7, False), (8, True)])
def test_probe_goes_stale_after_seven_days(tmp_path: Path, days_ago: int, stale: bool) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, _run("r1", days_ago, []))

    assert CorrectionLedger(ledger).probe(today=TODAY).stale is stale


def test_probe_counts_an_opened_run_that_never_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, _run("r1", 0, [], closed=False))

    probe = CorrectionLedger(ledger).probe(today=TODAY).to_dict()

    assert probe["unclosed"] == 1
    assert probe["never_run"] is True
    assert probe["stale"] is True


def test_a_corrupt_line_is_unreadable_by_name(tmp_path: Path) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, _run("r1", 0, ["a.md"]))
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    with pytest.raises(LedgerUnreadable, match=r"corrections\.jsonl:4"):
        CorrectionLedger(ledger).probe(today=TODAY)
    with pytest.raises(LedgerUnreadable, match=r"corrections\.jsonl:4"):
        CorrectionLedger(ledger).last_checked()


@pytest.mark.parametrize(
    "row",
    [
        ["a", "list"],
        {"event": "renamed", "run": "r1"},
        {"event": "closed", "run": "r1", "at": "not a time"},
        {"event": "verdict", "run": "r1"},
    ],
    ids=["not-an-object", "unknown-event", "bad-closed-at", "verdict-without-filename"],
)
def test_a_malformed_row_is_unreadable(tmp_path: Path, row: object) -> None:
    ledger = tmp_path / "corrections.jsonl"
    _write_rows(ledger, [row])  # type: ignore[list-item]

    with pytest.raises(LedgerUnreadable, match=r"corrections\.jsonl:1"):
        CorrectionLedger(ledger).last_checked()


def test_append_writes_every_row_in_one_write(tmp_path: Path, monkeypatch) -> None:
    """Verdict rows and the closing row land together, so no run closes without its clock."""
    ledger = CorrectionLedger(tmp_path / "data" / "corrections.jsonl")
    rows = _run("r1", 0, ["a.md", "b.md"])
    writes: list[str] = []
    real_open = Path.open

    def spy_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if self == ledger.path:
            real_write = handle.write
            handle.write = lambda text: writes.append(text) or real_write(text)
        return handle

    monkeypatch.setattr(Path, "open", spy_open)
    ledger.append(rows)

    assert len(writes) == 1
    assert [json.loads(line) for line in ledger.path.read_text().splitlines()] == rows


def test_last_checked_dates_by_the_writer_local_day(tmp_path: Path) -> None:
    """`at` carries its offset; the clock reads the calendar day it names, not UTC's."""
    ledger = tmp_path / "corrections.jsonl"
    late = datetime(2026, 11, 11, 23, 30, tzinfo=LOCAL).isoformat()
    _write_rows(
        ledger,
        [
            {"event": "opened", "run": "r1", "at": late},
            {"event": "verdict", "run": "r1", "filename": "a.md", "verdict": "confirmed"},
            {"event": "closed", "run": "r1", "at": late},
        ],
    )

    assert CorrectionLedger(ledger).last_checked() == {"a.md": date(2026, 11, 11)}
