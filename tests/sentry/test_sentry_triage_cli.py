# ABOUTME: Tests for scripts/sentry_triage.py — the exit-code contract and the two-run idempotency.
# ABOUTME: The client factory and the store are injected, so no live Sentry call and no token.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from oversteward.sentry.client import SentryConfigError
from oversteward.sentry.triage import TriageStore

from .fakes import AG_1, blind_sentry, empty_sentry, one_issue_sentry, two_project_sentry

SWEEP = ["sweep"]
RECORD = "record"
CLEAN_LINE = "nothing to triage"
BLIND = "could not look"


def _load_cli():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "sentry_triage.py"
    spec = importlib.util.spec_from_file_location("oversteward_sentry_triage_cli", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


@pytest.fixture
def store(tmp_path: Path) -> TriageStore:
    return TriageStore(
        ledger_path=tmp_path / "sentry" / "ledger.jsonl",
        pending_path=tmp_path / "sentry" / "pending.json",
    )


# --- sweep ------------------------------------------------------------------


def test_a_sweep_with_a_queue_exits_zero_and_lists_it(cli, store, capsys) -> None:
    code = cli.main(SWEEP, client_factory=two_project_sentry, store=store)

    assert code == cli.EXIT_OK
    assert AG_1 in capsys.readouterr().out


def test_a_swept_queue_is_snapshotted_so_record_needs_no_network(cli, store) -> None:
    cli.main(SWEEP, client_factory=one_issue_sentry, store=store)

    assert list(store.pending()) == [AG_1]


def test_a_drained_ledger_sweeps_clean_and_exits_zero(cli, store, capsys) -> None:
    code = cli.main(SWEEP, client_factory=empty_sentry, store=store)

    assert code == cli.EXIT_OK
    assert CLEAN_LINE in capsys.readouterr().out


def test_sweeping_twice_in_a_row_prints_the_same_clean_line(cli, store, capsys) -> None:
    assert cli.main(SWEEP, client_factory=empty_sentry, store=store) == cli.EXIT_OK
    first = capsys.readouterr().out

    assert cli.main(SWEEP, client_factory=empty_sentry, store=store) == cli.EXIT_OK

    assert capsys.readouterr().out == first


# --- "could not look" is never "nothing new" --------------------------------


def test_a_missing_token_exits_non_zero_with_could_not_look(cli, store, capsys) -> None:
    def no_token():
        raise SentryConfigError("SENTRY_API_TOKEN is not set")

    code = cli.main(SWEEP, client_factory=no_token, store=store)

    assert code == cli.EXIT_MISCONFIGURED
    captured = capsys.readouterr()
    assert BLIND in captured.err
    assert CLEAN_LINE not in captured.err + captured.out


def test_an_api_failure_exits_non_zero_with_could_not_look(cli, store, capsys) -> None:
    code = cli.main(SWEEP, client_factory=blind_sentry, store=store)

    assert code == cli.EXIT_COULD_NOT_LOOK
    captured = capsys.readouterr()
    assert BLIND in captured.err
    assert "HTTP 401" in captured.err
    assert captured.out == ""


def test_a_failed_sweep_writes_no_ledger_and_no_snapshot(cli, store) -> None:
    cli.main(SWEEP, client_factory=blind_sentry, store=store)

    assert not store.ledger_path.exists()
    assert not store.pending_path.exists()


# --- record -----------------------------------------------------------------


def test_recording_a_verdict_removes_the_issue_from_the_next_sweep(cli, store, capsys) -> None:
    cli.main(SWEEP, client_factory=one_issue_sentry, store=store)

    assert cli.main([RECORD, AG_1, "filed", "--ref", "AG#1"], store=store) == cli.EXIT_OK
    capsys.readouterr()
    cli.main(SWEEP, client_factory=one_issue_sentry, store=store)

    assert CLEAN_LINE in capsys.readouterr().out


def test_recording_an_unswept_short_id_exits_non_zero(cli, store, capsys) -> None:
    code = cli.main([RECORD, "AIGRANTHELPER-404", "fixed"], store=store)

    assert code == cli.EXIT_MISCONFIGURED
    assert "not in the last sweep" in capsys.readouterr().err


def test_the_resolve_flag_marks_the_issue_resolved_in_sentry(cli, store) -> None:
    fake = one_issue_sentry()
    cli.main(SWEEP, client_factory=lambda: fake, store=store)

    cli.main(
        [RECORD, AG_1, "noise-resolved", "--ref", "retired cron", "--resolve"],
        client_factory=lambda: fake,
        store=store,
    )

    assert fake.resolved == [("aigranthelper1", "retired cron")]


def test_a_failed_resolve_records_no_verdict(cli, store) -> None:
    cli.main(SWEEP, client_factory=one_issue_sentry, store=store)

    code = cli.main(
        [RECORD, AG_1, "fixed", "--resolve"],
        client_factory=blind_sentry,
        store=store,
    )

    assert code == cli.EXIT_COULD_NOT_LOOK
    assert store.recorded() == {}


def test_an_unknown_verdict_is_rejected_by_the_parser(cli, store) -> None:
    with pytest.raises(SystemExit):
        cli.main([RECORD, AG_1, "later"], store=store)
