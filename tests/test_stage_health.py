# ABOUTME: Tests for the /stage-health sweep — exit-code passthrough, schema refusal, verdict ledger.
# ABOUTME: The producer and GitHub are injected fakes; one test drives a real subprocess stub.

from __future__ import annotations

import importlib.util
import json
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oversteward.board.client import GhError, NotFoundError
from oversteward.stage_health.sources import (
    GithubIssueStates,
    GrantspiderHealthCli,
    IssueStateUnavailableError,
    ProducerConfigError,
    ProducerRun,
    ProducerUnavailableError,
    checkout_from_registry,
)
from oversteward.stage_health.triage import (
    StageHealthUnreadable,
    VerdictError,
    VerdictStore,
    parse_document,
    parse_ref,
    record,
    sweep,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WHEN = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ATTEMPTS_KEY = "fetch_attempts_below_median@deep_crawl"
LEDGER_KEY = "ledger_stale"


# --- fixtures ---------------------------------------------------------------


def _finding(severity: str, rule: str, stage: str | None, message: str = "m") -> dict:
    return {"severity": severity, "rule": rule, "stage": stage, "message": message}


def _doc(status: str = "measured", **overrides) -> dict:
    """A ``grantspider dq health --json`` document, schema 1, as the producer prints it."""
    exit_code = {"measured": 0, "unreadable": 1, "no_rows": 2}[status]
    measured = status == "measured"
    doc = {
        "schema": 1,
        "status": status,
        "exit_code": exit_code,
        "generated_at": "2026-09-24T12:00:00+00:00",
        "window": {"days": 7, "first_day": "2026-09-17", "last_day": "2026-09-23"},
        "latest_day": "2026-09-23" if measured else None,
        "ledger_newest_computed_at": "2026-09-24T03:00:00+00:00" if measured else None,
        "counts": {"stages": 9 if measured else 0, "days": 7 if measured else 0},
        "verdict": "RED" if measured else None,
        "findings": [
            _finding("RED", "fetch_attempts_below_median", "deep_crawl", "412 attempted"),
            _finding("RED", "ledger_stale", None, "newest row 40 h old"),
            _finding("YELLOW", "canaries_not_configured", None, "no canary ran"),
        ]
        if measured
        else [],
        "not_evaluated": [{"rule": "stale_share_above_window", "stage": "keep_current",
                           "reason": "windows not configured"}] if measured else [],
        "stages": {
            "deep_crawl": {
                "attempted": [
                    {"day": "2026-09-22", "value": 9000.0, "sample_size": 1},
                    {"day": "2026-09-23", "value": 412.0, "sample_size": 1},
                ]
            }
        }
        if measured
        else {},
        "schedules": {"basis": "declared", "states": {}},
        "canaries": {"configured": False, "evaluated": None},
        "error": "database unreadable: OperationalError" if status == "unreadable" else None,
    }
    doc.update(overrides)
    return doc


def _run(doc: dict | None, returncode: int | None = None) -> ProducerRun:
    """The producer's process result: the document on stdout, its own exit code."""
    code = doc["exit_code"] if returncode is None and doc else returncode
    return ProducerRun(returncode=code, stdout="" if doc is None else json.dumps(doc))


class FakeProducer:
    def __init__(self, result: ProducerRun | Exception) -> None:
        self._result = result

    def run(self) -> ProducerRun:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeIssues:
    """GitHub issue states by ``(repo, number)``; an unknown ref is missing."""

    def __init__(self, states: dict[tuple[str, int], str] | None = None, fail: bool = False):
        self._states = states or {}
        self._fail = fail
        self.asked: list[tuple[str, int]] = []

    def __call__(self, repo: str, number: int) -> str:
        self.asked.append((repo, number))
        if self._fail:
            raise IssueStateUnavailableError("gh api failed")
        return self._states.get((repo, number), "missing")


@pytest.fixture
def store(tmp_path: Path) -> VerdictStore:
    return VerdictStore(
        ledger_path=tmp_path / "stage-health" / "ledger.jsonl",
        pending_path=tmp_path / "stage-health" / "pending.json",
    )


def _load_cli():
    script_path = REPO_ROOT / "scripts" / "stage_health.py"
    spec = importlib.util.spec_from_file_location("oversteward_stage_health_cli", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


def _sweep_cli(cli, store, result, issues=None, argv=("sweep",)) -> int:
    return cli.main(
        list(argv),
        producer_factory=lambda _days: FakeProducer(result),
        store=store,
        issue_states=issues if issues is not None else FakeIssues(),
    )


# --- exit codes pass through unchanged ---------------------------------------


@pytest.mark.parametrize("status", ["measured", "unreadable", "no_rows"])
def test_the_producer_exit_code_passes_through_unchanged(cli, store, status) -> None:
    doc = _doc(status)
    assert _sweep_cli(cli, store, _run(doc)) == doc["exit_code"]


def test_no_rows_is_reported_as_the_asset_not_running_never_as_a_clean_sweep(
    cli, store, capsys
) -> None:
    code = _sweep_cli(cli, store, _run(_doc("no_rows")))

    out = capsys.readouterr().out
    assert code == 2
    assert "stage_health_snapshot asset is not running" in out
    assert "ledger current" not in out


def test_an_unreadable_ledger_prints_the_producer_error_and_exits_one(cli, store, capsys) -> None:
    code = _sweep_cli(cli, store, _run(_doc("unreadable")))

    assert code == 1
    assert "database unreadable: OperationalError" in capsys.readouterr().err


def test_a_real_subprocess_exit_code_is_passed_through(tmp_path: Path) -> None:
    """End to end through subprocess: a stub `grantspider` exiting 1 reads as 1, not 2."""
    checkout = tmp_path / "grantspider"
    binary = checkout / ".venv" / "bin" / "grantspider"
    binary.parent.mkdir(parents=True)
    (checkout / "doc.json").write_text(json.dumps(_doc("unreadable")), encoding="utf-8")
    binary.write_text('#!/bin/sh\ncat doc.json\nexit 1\n', encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)

    result = GrantspiderHealthCli(checkout).run()

    assert result.returncode == 1
    assert parse_document(result.stdout, result.returncode).exit_code == 1


def test_a_usage_error_exit_two_without_a_document_is_unreadable_not_no_rows(
    cli, store, capsys
) -> None:
    code = _sweep_cli(cli, store, ProducerRun(returncode=2, stdout="Usage: grantspider dq ..."))

    assert code == 1
    assert "could not read" in capsys.readouterr().err


def test_a_producer_that_cannot_be_started_exits_one(cli, store, capsys) -> None:
    code = _sweep_cli(cli, store, ProducerUnavailableError("no such file"))

    assert code == 1
    assert "could not read" in capsys.readouterr().err


def test_no_grantspider_context_in_the_registry_exits_two(cli, store, capsys) -> None:
    def unconfigured(_days):
        raise ProducerConfigError("no grantspider context")

    code = cli.main(["sweep"], producer_factory=unconfigured, store=store,
                    issue_states=FakeIssues())

    assert code == 2
    assert "not configured" in capsys.readouterr().err


# --- the schema version is refused, not guessed at ---------------------------


@pytest.mark.parametrize("schema", [2, 0, "1", True, None])
def test_an_unknown_schema_version_is_refused_as_could_not_read(cli, store, capsys, schema):
    code = _sweep_cli(cli, store, _run(_doc("measured", schema=schema)))

    assert code == 1
    err = capsys.readouterr().err
    assert "could not read" in err
    assert "schema" in err


def test_a_document_without_a_schema_key_is_refused(store) -> None:
    doc = _doc("measured")
    del doc["schema"]
    with pytest.raises(StageHealthUnreadable, match="schema"):
        parse_document(json.dumps(doc), 0)


def test_a_document_whose_exit_code_disagrees_with_the_process_is_refused() -> None:
    with pytest.raises(StageHealthUnreadable, match="exit"):
        parse_document(json.dumps(_doc("no_rows")), 0)


def test_a_document_whose_status_disagrees_with_its_exit_code_is_refused() -> None:
    doc = _doc("measured", exit_code=2)
    with pytest.raises(StageHealthUnreadable, match="status"):
        parse_document(json.dumps(doc), 2)


def test_a_red_finding_without_a_rule_is_refused_rather_than_dropped() -> None:
    doc = _doc("measured", findings=[{"severity": "RED", "stage": "x", "message": "m"}])
    with pytest.raises(StageHealthUnreadable, match="rule"):
        parse_document(json.dumps(doc), 0)


# --- a clean run names its count ---------------------------------------------


def test_a_clean_run_names_stages_days_and_canaries(cli, store, capsys) -> None:
    doc = _doc("measured", findings=[], verdict="GREEN")
    assert _sweep_cli(cli, store, _run(doc)) == 0

    out = capsys.readouterr().out
    assert "9 stages, 7 of 7 days, canaries not configured" in out
    assert "ledger current" in out


def test_configured_canaries_are_counted_by_number(cli, store, capsys) -> None:
    doc = _doc("measured", findings=[], verdict="GREEN",
               canaries={"configured": True, "evaluated": 12})
    _sweep_cli(cli, store, _run(doc))

    assert "12 canaries evaluated" in capsys.readouterr().out


def test_the_per_stage_table_prints_the_latest_value(cli, store, capsys) -> None:
    _sweep_cli(cli, store, _run(_doc("measured")))

    assert re.search(r"deep_crawl\s+attempted\s+412\b", capsys.readouterr().out)


# --- a RED without a verdict comes back ---------------------------------------


def test_an_unruled_red_reappears_on_the_next_run(cli, store, capsys) -> None:
    for _ in range(2):
        assert _sweep_cli(cli, store, _run(_doc("measured"))) == 0
        out = capsys.readouterr().out
        assert ATTEMPTS_KEY in out
        assert "2 RED row(s) awaiting a verdict" in out


def test_a_yellow_finding_never_joins_the_verdict_queue(store) -> None:
    result = sweep(parse_document(json.dumps(_doc("measured")), 0), store, FakeIssues())

    assert {q.finding.key for q in result.queue} == {ATTEMPTS_KEY, LEDGER_KEY}


def test_a_recorded_verdict_takes_the_row_out_of_the_queue(cli, store, capsys) -> None:
    _sweep_cli(cli, store, _run(_doc("measured")))
    assert cli.main(["record", LEDGER_KEY, "fixed", "--ref", "OS#999"], store=store) == 0
    capsys.readouterr()

    _sweep_cli(cli, store, _run(_doc("measured")))

    out = capsys.readouterr().out
    assert "1 RED row(s) awaiting a verdict" in out
    assert f"FIXED@2026-09-23  {LEDGER_KEY}" in out  # listed as ruled on, not silently gone


def test_fixed_covers_only_the_ledger_day_it_was_recorded_against(store) -> None:
    today = parse_document(json.dumps(_doc("measured")), 0)
    sweep(today, store, FakeIssues())
    store.save_pending(today)
    record(store, ATTEMPTS_KEY, "fixed", "", WHEN)

    tomorrow = parse_document(json.dumps(_doc("measured", latest_day="2026-09-24")), 0)
    result = sweep(tomorrow, store, FakeIssues())

    queued = {q.finding.key: q.reason for q in result.queue}
    assert ATTEMPTS_KEY in queued
    assert "2026-09-23" in queued[ATTEMPTS_KEY]


def test_known_reprints_as_known_while_its_ref_is_open(cli, store, capsys) -> None:
    issues = FakeIssues({("NathanKrupa/grantspider", 2805): "open"})
    _sweep_cli(cli, store, _run(_doc("measured")), issues)
    cli.main(["record", ATTEMPTS_KEY, "known", "--ref", "GS#2805"], store=store)
    capsys.readouterr()

    for _ in range(2):
        _sweep_cli(cli, store, _run(_doc("measured")), issues)
        out = capsys.readouterr().out
        assert f"KNOWN→GS#2805  {ATTEMPTS_KEY}" in out
        assert "1 RED row(s) awaiting a verdict" in out


def test_known_row_reappears_once_its_ref_closes(cli, store, capsys) -> None:
    open_issue = FakeIssues({("NathanKrupa/grantspider", 2805): "open"})
    _sweep_cli(cli, store, _run(_doc("measured")), open_issue)
    cli.main(["record", ATTEMPTS_KEY, "known", "--ref", "GS#2805"], store=store)

    closed = FakeIssues({("NathanKrupa/grantspider", 2805): "closed"})
    capsys.readouterr()
    _sweep_cli(cli, store, _run(_doc("measured")), closed)

    out = capsys.readouterr().out
    assert "KNOWN→" not in out
    assert "2 RED row(s) awaiting a verdict" in out
    assert "GS#2805 is closed" in out


def test_filed_row_reappears_when_its_ref_does_not_exist(store) -> None:
    doc = parse_document(json.dumps(_doc("measured")), 0)
    store.save_pending(doc)
    record(store, ATTEMPTS_KEY, "filed", "GS#123456", WHEN)

    result = sweep(doc, store, FakeIssues())

    queued = {q.finding.key: q.reason for q in result.queue}
    assert "GS#123456 does not exist" in queued[ATTEMPTS_KEY]


def test_an_unreadable_ref_fails_the_sweep_rather_than_reading_as_tracked(
    cli, store, capsys
) -> None:
    doc = parse_document(json.dumps(_doc("measured")), 0)
    store.save_pending(doc)
    record(store, ATTEMPTS_KEY, "known", "GS#2805", WHEN)

    code = _sweep_cli(cli, store, _run(_doc("measured")), FakeIssues(fail=True))

    assert code == 1
    assert "could not read" in capsys.readouterr().err


def test_an_unexpected_issue_state_is_unreadable(store) -> None:
    doc = parse_document(json.dumps(_doc("measured")), 0)
    store.save_pending(doc)
    record(store, ATTEMPTS_KEY, "known", "GS#2805", WHEN)

    with pytest.raises(StageHealthUnreadable, match="state"):
        sweep(doc, store, FakeIssues({("NathanKrupa/grantspider", 2805): "merged?"}))


# --- recording ----------------------------------------------------------------


def test_there_is_no_later_verdict(cli, store) -> None:
    with pytest.raises(SystemExit):
        cli.main(["record", ATTEMPTS_KEY, "later"], store=store)


@pytest.mark.parametrize("verdict", ["filed", "known"])
def test_filed_and_known_require_an_issue_ref(store, verdict) -> None:
    store.save_pending(parse_document(json.dumps(_doc("measured")), 0))
    for bad in ("", "soon", "GS#", "XX#12", "GS#12a"):
        with pytest.raises(VerdictError):
            record(store, ATTEMPTS_KEY, verdict, bad, WHEN)


def test_a_key_that_was_not_red_in_the_last_sweep_is_refused(cli, store, capsys) -> None:
    store.save_pending(parse_document(json.dumps(_doc("measured")), 0))

    assert cli.main(["record", "canaries_not_configured", "fixed"], store=store) == 2
    assert "not a RED row" in capsys.readouterr().err


def test_a_ruling_is_stamped_with_the_ledger_day_it_ruled_on(store) -> None:
    store.save_pending(parse_document(json.dumps(_doc("measured")), 0))

    ruling = record(store, LEDGER_KEY, "fixed", "", WHEN)

    assert ruling.ledger_day == "2026-09-23"
    assert store.rulings()[LEDGER_KEY] == ruling


def test_a_damaged_ledger_line_is_skipped_not_fatal(store) -> None:
    store.save_pending(parse_document(json.dumps(_doc("measured")), 0))
    record(store, LEDGER_KEY, "fixed", "", WHEN)
    with store.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    assert list(store.rulings()) == [LEDGER_KEY]


def test_refs_map_to_their_repositories() -> None:
    assert parse_ref("GS#2805").repo == "NathanKrupa/grantspider"
    assert parse_ref("OS#536").repo == "NathanKrupa/OverSteward"
    assert parse_ref("AG#12").repo == "NathanKrupa/aigranthelper"
    assert parse_ref("GS#2805").number == 2805


# --- sources ------------------------------------------------------------------


def test_the_producer_runs_the_json_command_from_the_grantspider_checkout(tmp_path) -> None:
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["cwd"] = argv, kwargs["cwd"]
        return type("P", (), {"returncode": 0, "stdout": "{}"})()

    GrantspiderHealthCli(tmp_path, days=3, run=fake_run).run()

    assert seen["argv"] == [str(tmp_path / ".venv" / "bin" / "grantspider"),
                            "dq", "health", "--json", "--days", "3"]
    assert seen["cwd"] == tmp_path


def test_a_missing_producer_binary_is_unavailable(tmp_path) -> None:
    with pytest.raises(ProducerUnavailableError):
        GrantspiderHealthCli(tmp_path / "nowhere").run()


def test_the_checkout_comes_from_the_registry() -> None:
    registry = {"contexts": [{"id": "fiscus", "local_path": "/f"},
                             {"id": "grantspider", "local_path": "/g"}]}
    assert checkout_from_registry(registry) == Path("/g")
    with pytest.raises(ProducerConfigError):
        checkout_from_registry({"contexts": [{"id": "fiscus", "local_path": "/f"}]})


def test_github_issue_states_map_404_to_missing_and_failures_to_unavailable() -> None:
    def answer(payload_or_exc):
        def run(_args):
            if isinstance(payload_or_exc, Exception):
                raise payload_or_exc
            return payload_or_exc
        return run

    assert GithubIssueStates(run=answer({"state": "closed"}))("o/r", 1) == "closed"
    assert GithubIssueStates(run=answer(NotFoundError("HTTP 404")))("o/r", 1) == "missing"
    with pytest.raises(IssueStateUnavailableError):
        GithubIssueStates(run=answer(GhError("HTTP 502")))("o/r", 1)
    with pytest.raises(IssueStateUnavailableError):
        GithubIssueStates(run=answer(["not", "a", "dict"]))("o/r", 1)


# --- the session-start doctrine -------------------------------------------------


def _session_start_block() -> str:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    section = text.split("## Session start", 1)[1].split("\n## ", 1)[0]
    return section.split("```bash", 1)[1].split("```", 1)[0]


def test_claude_md_lists_stage_health_as_a_session_start_sweep() -> None:
    lines = [line for line in _session_start_block().splitlines() if "stage_health.py" in line]
    assert lines == [
        ".venv/bin/python scripts/stage_health.py sweep       # what GS's pipeline stopped doing"
    ]


@pytest.mark.parametrize("doc", ["CLAUDE.md", ".claude/skills/stage-health/SKILL.md"])
def test_no_stage_health_invocation_is_piped_through_a_filter(doc) -> None:
    text = (REPO_ROOT / doc).read_text(encoding="utf-8")
    invocations = [line for line in text.splitlines() if re.search(r"stage_health\.py|\$SH\b", line)]
    assert invocations, f"{doc} never invokes the sweep"
    assert not [line for line in invocations if re.search(r"\|\s*(tail|head)\b", line)]
