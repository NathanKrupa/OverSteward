# ABOUTME: Tests for the /stage-health sweep — exit-code passthrough, schema refusal, verdict ledger.
# ABOUTME: The producer and GitHub are injected fakes; one test drives a real subprocess stub.

from __future__ import annotations

import importlib.util
import json
import re
import stat
import subprocess
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
    ProducerTimeoutError,
    ProducerUnavailableError,
    RailwayHealthSsh,
    checkout_from_registry,
    error_names,
)
from oversteward.stage_health.triage import (
    HealthReader,
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
        producer_factory=lambda _days: HealthReader(FakeProducer(result)),
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
    doc = _doc("measured", findings=[], verdict="GREEN", counts={"stages": 9, "days": 5})
    assert _sweep_cli(cli, store, _run(doc)) == 0

    out = capsys.readouterr().out
    assert "9 stages, 5 of 7 days, canaries not configured" in out
    assert "ledger current" in out


def _canary_headline(cli, store, capsys, **canaries) -> str:
    """The first line a sweep prints, for a document carrying ``canaries``."""
    doc = _doc("measured", findings=[], verdict="GREEN",
               canaries={"configured": True, **canaries})
    _sweep_cli(cli, store, _run(doc))
    return capsys.readouterr().out.splitlines()[0]


def test_passing_canaries_headline_evaluated_expected_and_failed(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=12, failed=0)

    assert headline.endswith("canaries: 12 of 12 evaluated, 0 failed.")


def test_a_failed_canary_is_red_in_the_headline(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=12, failed=3)

    assert headline.endswith("canaries RED: 12 of 12 evaluated, 3 failed.")


def test_evaluated_short_of_expected_is_red_in_the_headline(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=10, failed=0)

    assert headline.endswith("canaries RED: 10 of 12 evaluated (evaluated ≠ expected), 0 failed.")


def test_evaluated_beyond_expected_is_red_in_the_headline(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=13, failed=0)

    assert headline.endswith("canaries RED: 13 of 12 evaluated (evaluated ≠ expected), 0 failed.")


def test_configured_canaries_without_an_expected_count_are_red(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, evaluated=12, failed=0)

    assert headline.endswith("canaries RED: 12 of ? evaluated (evaluated ≠ expected), 0 failed.")


def test_no_canary_rows_is_a_finding_not_zero_evaluated(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=None, failed=None)

    assert headline.endswith("canaries RED: no canary rows (12 expected).")
    assert "0 canaries" not in headline


def test_a_missing_failed_count_is_red_rather_than_read_as_zero(cli, store, capsys) -> None:
    headline = _canary_headline(cli, store, capsys, expected=12, evaluated=12, failed=None)

    assert headline.endswith("canaries RED: 12 of 12 evaluated, failed count not reported.")


def test_the_pre_2834_canary_block_parses_without_expected_or_failed() -> None:
    doc = _doc("measured", canaries={"configured": False, "evaluated": None})

    parsed = parse_document(json.dumps(doc), 0)

    assert (parsed.canaries_expected, parsed.canaries_failed) == (None, None)


def test_the_canary_counts_are_read_from_the_document() -> None:
    canaries = {"configured": True, "expected": 12, "evaluated": 11, "failed": 3}

    parsed = parse_document(json.dumps(_doc("measured", canaries=canaries)), 0)

    assert (parsed.canaries_expected, parsed.canaries_evaluated, parsed.canaries_failed) == (
        12, 11, 3,
    )


@pytest.mark.parametrize("key", ["expected", "failed"])
@pytest.mark.parametrize("value", ["3", True, 3.0])
def test_a_canary_count_of_the_wrong_type_is_refused(key: str, value) -> None:
    canaries = {"configured": True, "expected": 12, "evaluated": 12, "failed": 0, key: value}

    with pytest.raises(StageHealthUnreadable, match=f"canaries.{key}"):
        parse_document(json.dumps(_doc("measured", canaries=canaries)), 0)


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


def test_the_last_ruling_for_a_row_wins(store) -> None:
    doc = parse_document(json.dumps(_doc("measured")), 0)
    store.save_pending(doc)
    record(store, ATTEMPTS_KEY, "known", "GS#1", WHEN)
    record(store, ATTEMPTS_KEY, "filed", "GS#2", WHEN)
    issues = FakeIssues({("NathanKrupa/grantspider", 1): "closed",
                         ("NathanKrupa/grantspider", 2): "open"})

    result = sweep(doc, store, issues)

    assert [(t.finding.key, t.ruling.ref) for t in result.tracked] == [(ATTEMPTS_KEY, "GS#2")]


@pytest.mark.parametrize(
    ("verdict", "ref", "reason"),
    [("later", "GS#1", "unknown verdict"), ("known", "soon", "unreadable ref")],
)
def test_a_damaged_ruling_sends_its_row_back_to_the_queue(store, verdict, ref, reason) -> None:
    doc = parse_document(json.dumps(_doc("measured")), 0)
    line = {"key": ATTEMPTS_KEY, "verdict": verdict, "ref": ref, "ledgerDay": "2026-09-23"}
    store.ledger_path.parent.mkdir(parents=True)
    store.ledger_path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    result = sweep(doc, store, FakeIssues({("NathanKrupa/grantspider", 1): "open"}))

    queued = {q.finding.key: q.reason for q in result.queue}
    assert reason in queued[ATTEMPTS_KEY]


def test_record_before_any_measured_sweep_is_refused(store) -> None:
    with pytest.raises(VerdictError, match="no measured sweep"):
        record(store, ATTEMPTS_KEY, "fixed", "", WHEN)


def test_a_boolean_exit_code_is_refused_even_where_it_equals_one() -> None:
    with pytest.raises(StageHealthUnreadable, match="exit_code"):
        parse_document(json.dumps(_doc("unreadable", exit_code=True)), 1)


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


@pytest.mark.parametrize("status", ["no_rows", "unreadable"])
def test_only_a_measured_sweep_replaces_the_pending_snapshot(cli, store, status) -> None:
    _sweep_cli(cli, store, _run(_doc("measured")))
    before = store.pending_path.read_bytes()

    _sweep_cli(cli, store, _run(_doc(status)))

    assert store.pending_path.read_bytes() == before


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
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    GrantspiderHealthCli(tmp_path, days=3, run=fake_run).run()

    assert seen["argv"] == [str(tmp_path / ".venv" / "bin" / "grantspider"),
                            "dq", "health", "--json", "--days", "3"]
    assert seen["cwd"] == tmp_path


def test_a_missing_producer_binary_is_unavailable(tmp_path) -> None:
    with pytest.raises(ProducerUnavailableError):
        GrantspiderHealthCli(tmp_path / "nowhere").run()


def test_a_local_producer_timeout_is_a_timeout_the_fallback_can_see(tmp_path) -> None:
    def hang(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    with pytest.raises(ProducerTimeoutError, match="timed out after 5s"):
        GrantspiderHealthCli(tmp_path, timeout=5, run=hang).run()


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


# --- the railway-ssh fallback (OS#540) -----------------------------------------

#: What the Railway CLI prints around a remote command's output (measured 2026-09-25).
RAILWAY_NOISE_BEFORE = (
    "Using SSH key from file /home/natha/.ssh/claude-code-grantspider-readonly\n"
    "Config as Code (railway.json / railway.toml) is deprecated and will be removed.\n"
    "Existing files keep working until 2026-12-01.\n"
)
RAILWAY_NOISE_AFTER = "Connection to grantspider closed.\n"


def _connection_failure(error_class: str = "OperationalError") -> ProducerRun:
    """The local producer behind the VPN: it ran, and could not reach its database."""
    return _run(_doc("unreadable", error=f"database unreadable: {error_class}"))


class CountingProducer(FakeProducer):
    def __init__(self, result: ProducerRun | Exception) -> None:
        super().__init__(result)
        self.calls = 0

    def run(self) -> ProducerRun:
        self.calls += 1
        return super().run()


def _railway_stdout(doc: dict) -> str:
    """The remote document as ``railway ssh`` prints it: indented, wrapped in CLI noise."""
    return RAILWAY_NOISE_BEFORE + json.dumps(doc, indent=2) + "\n" + RAILWAY_NOISE_AFTER


def _railway(tmp_path: Path, stdout: str | Exception, returncode: int = 0, seen=None):
    def fake_run(argv, **kwargs):
        if seen is not None:
            seen.update(argv=argv, **kwargs)
        if isinstance(stdout, Exception):
            raise stdout
        return type("P", (), {"returncode": returncode, "stdout": stdout, "stderr": ""})()

    return RailwayHealthSsh(tmp_path, days=3, run=fake_run)


def _sweep_routes(cli, store, local, remote) -> int:
    return cli.main(
        ["sweep"],
        producer_factory=lambda _days: HealthReader(local, remote),
        store=store,
        issue_states=FakeIssues(),
    )


@pytest.mark.parametrize("status", ["measured", "no_rows"])
def test_a_local_connection_failure_is_answered_by_railway_ssh(
    cli, store, capsys, tmp_path, status
) -> None:
    doc = _doc(status)
    remote = _railway(tmp_path, _railway_stdout(doc), returncode=doc["exit_code"])

    code = _sweep_routes(cli, store, FakeProducer(_connection_failure()), remote)

    assert code == doc["exit_code"]
    assert "via: railway-ssh" in capsys.readouterr().out.splitlines()[0]


def test_an_interface_error_is_a_connection_failure_too(cli, store, capsys, tmp_path) -> None:
    remote = _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=2)

    code = _sweep_routes(cli, store, FakeProducer(_connection_failure("InterfaceError")), remote)

    assert code == 2
    assert "via: railway-ssh" in capsys.readouterr().out


def test_a_measured_document_carrying_an_error_never_falls_back(cli, store, capsys) -> None:
    local = _run(_doc("measured", error="database unreadable: OperationalError"))
    remote = CountingProducer(_run(_doc("no_rows")))

    code = _sweep_routes(cli, store, FakeProducer(local), remote)

    assert (code, remote.calls) == (0, 0)
    assert "via: local" in capsys.readouterr().out


def test_an_unreadable_remote_document_names_its_route(cli, store, capsys, tmp_path) -> None:
    """Production's answer on 2026-09-25 before GS#2842 shipped its thresholds file."""
    doc = _doc("unreadable", error="thresholds: cannot read config/stage_health_thresholds.yaml")
    remote = _railway(tmp_path, _railway_stdout(doc), returncode=1)

    code = _sweep_routes(cli, store, FakeProducer(_connection_failure()), remote)

    err = capsys.readouterr().err
    assert code == 1
    assert "(via: railway-ssh; local: database unreadable: OperationalError): thresholds: " in err


def test_the_default_sweep_carries_the_railway_route(cli) -> None:
    reader = cli.default_producer(3)

    assert isinstance(reader.local, GrantspiderHealthCli)
    assert isinstance(reader.remote, RailwayHealthSsh)
    assert reader.remote.argv()[-2:] == ["--days", "3"]


def test_a_local_timeout_is_answered_by_railway_ssh(cli, store, capsys, tmp_path) -> None:
    remote = _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=2)

    code = _sweep_routes(cli, store, FakeProducer(ProducerTimeoutError("timed out")), remote)

    assert code == 2
    assert "via: railway-ssh" in capsys.readouterr().out


def test_the_fallback_is_one_attempt_never_a_loop(cli, store) -> None:
    local = CountingProducer(_connection_failure())
    remote = CountingProducer(_run(_doc("no_rows")))

    assert _sweep_routes(cli, store, local, remote) == 2
    assert (local.calls, remote.calls) == (1, 1)


def test_a_local_timeout_with_no_remote_route_exits_one(cli, store, capsys) -> None:
    code = _sweep_cli(cli, store, ProducerTimeoutError("grantspider timed out after 600s"))

    assert code == 1
    assert "timed out after 600s" in capsys.readouterr().err


def test_local_no_rows_is_an_answer_and_never_falls_back(cli, store, capsys) -> None:
    remote = CountingProducer(_run(_doc("measured")))

    code = _sweep_routes(cli, store, FakeProducer(_run(_doc("no_rows"))), remote)

    assert (code, remote.calls) == (2, 0)
    assert "via: local" in capsys.readouterr().out


def test_a_local_measurement_names_its_route_and_never_falls_back(cli, store, capsys) -> None:
    remote = CountingProducer(_run(_doc("no_rows")))

    code = _sweep_routes(cli, store, FakeProducer(_run(_doc("measured"))), remote)

    assert (code, remote.calls) == (0, 0)
    assert "via: local" in capsys.readouterr().out.splitlines()[0]


@pytest.mark.parametrize(
    "local",
    [
        _run(_doc("unreadable", error="thresholds: no such file")),
        _run(_doc("unreadable", error="database unreadable: ProgrammingError")),
        ProducerUnavailableError("could not run grantspider: FileNotFoundError"),
    ],
    ids=["thresholds", "not-a-connection-error", "no-binary"],
)
def test_a_local_failure_that_is_not_a_connection_failure_never_falls_back(
    cli, store, capsys, local
) -> None:
    remote = CountingProducer(_run(_doc("measured")))

    code = _sweep_routes(cli, store, FakeProducer(local), remote)

    assert (code, remote.calls) == (1, 0)
    assert "could not read" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("failure", "returncode", "reason"),
    [
        (FileNotFoundError("railway"), 0, "railway CLI not found"),
        (subprocess.TimeoutExpired(["railway"], 120), 0, "timed out after 120s"),
        (RAILWAY_NOISE_BEFORE + "No linked project found.\n", 1, "exited 1"),
        (RAILWAY_NOISE_BEFORE, 2, "exited 2"),
    ],
    ids=["absent", "timeout", "not-linked", "warnings-only-exit-two"],
)
def test_a_failing_fallback_exits_one_naming_its_reason(
    cli, store, capsys, tmp_path, failure, returncode, reason
) -> None:
    remote = _railway(tmp_path, failure, returncode=returncode)

    code = _sweep_routes(cli, store, FakeProducer(_connection_failure()), remote)

    err = capsys.readouterr().err
    assert code == 1
    assert reason in err
    assert "railway-ssh" in err
    assert "OperationalError" in err  # the local failure that sent it there is named too


def test_warning_text_alone_on_a_zero_exit_is_not_a_pass(cli, store, capsys, tmp_path) -> None:
    remote = _railway(tmp_path, RAILWAY_NOISE_BEFORE + RAILWAY_NOISE_AFTER, returncode=0)

    code = _sweep_routes(cli, store, FakeProducer(_connection_failure()), remote)

    assert code == 1
    assert "no health document" in capsys.readouterr().err


def test_the_railway_noise_around_the_document_is_discarded(tmp_path) -> None:
    doc = _doc("measured")
    result = _railway(tmp_path, _railway_stdout(doc), returncode=0).run()

    assert "Config as Code" not in result.stdout
    assert "Using SSH key" not in result.stdout
    assert json.loads(result.stdout) == doc
    assert parse_document(result.stdout, result.returncode).exit_code == 0


def test_the_remote_exit_code_is_the_one_checked_against_the_document(tmp_path) -> None:
    result = _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=0).run()

    with pytest.raises(StageHealthUnreadable, match="exit"):
        parse_document(result.stdout, result.returncode)


def test_railway_ssh_runs_the_producer_in_production_from_the_checkout(tmp_path) -> None:
    seen: dict = {}
    _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=2, seen=seen).run()

    assert seen["argv"] == [
        "railway", "ssh", "--service", "grantspider", "--environment", "production",
        "--", "grantspider", "dq", "health", "--json", "--days", "3",
    ]
    assert seen["cwd"] == tmp_path
    assert seen["timeout"] == 120.0
    assert seen["stdin"] == subprocess.DEVNULL


# --- a connect failure before the producer can print a document (OS#542) --------

#: The tail of the GrantSpider migration guard's uncaught traceback behind the VPN:
#: the guard connects before ``dq health`` runs, so stdout is empty.
GUARD_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/home/natha/grantspider/src/grantspider/db/migration_guard.py", line 116\n'
    "psycopg.OperationalError: connection failed: connection to server at \"203.0.113.9\", "
    "port 5432 failed: timeout expired\n"
    "The above exception was the direct cause of the following exception:\n"
    "sqlalchemy.exc.OperationalError: (psycopg.OperationalError) connection failed: "
    "postgresql://neondb_owner:hunter2secret@ep-x.neon.tech/neondb?sslmode=require\n"
    "(Background on this error at: https://sqlalche.me/e/20/e3q8)\n"
)


def _no_document(stderr: str, returncode: int = 1) -> ProducerRun:
    return ProducerRun(returncode=returncode, stdout="", stderr_errors=error_names(stderr))


def test_a_connect_failure_with_no_document_is_answered_by_railway_ssh(
    cli, store, capsys, tmp_path
) -> None:
    remote = _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=2)

    code = _sweep_routes(cli, store, FakeProducer(_no_document(GUARD_TRACEBACK)), remote)

    out = capsys.readouterr().out
    assert code == 2
    assert "via: railway-ssh; local: OperationalError at connect" in out.splitlines()[0]


@pytest.mark.parametrize(
    "stderr",
    [
        "sqlalchemy.exc.InterfaceError: connection is closed\n",
        "sqlalchemy.exc.OperationalError: connection failed\n",
        "psycopg.OperationalError: connection failed\n",
        "psycopg.InterfaceError: connection is closed\n",
    ],
    ids=["sqlalchemy-interface", "sqlalchemy-operational", "psycopg-operational",
         "psycopg-interface"],
)
def test_each_connection_class_on_stderr_falls_back(cli, store, tmp_path, stderr) -> None:
    remote = CountingProducer(_run(_doc("no_rows")))

    code = _sweep_routes(cli, store, FakeProducer(_no_document(stderr)), remote)

    assert (code, remote.calls) == (2, 1)


@pytest.mark.parametrize(
    ("stderr", "returncode"),
    [
        ("ImportError: cannot import name 'defs' from 'grantspider.orchestration'\n", 1),
        ("sqlalchemy.exc.ProgrammingError: relation \"x\" does not exist\n", 1),
        ("OperationalError: something unqualified\n", 1),
        (GUARD_TRACEBACK, 2),
        ("", 1),
    ],
    ids=["import-error", "not-a-connection-class", "unqualified", "exit-two", "silent"],
)
def test_any_other_no_document_failure_never_falls_back(
    cli, store, capsys, stderr, returncode
) -> None:
    remote = CountingProducer(_run(_doc("measured")))

    code = _sweep_routes(cli, store, FakeProducer(_no_document(stderr, returncode)), remote)

    assert (code, remote.calls) == (1, 0)
    assert "printed no JSON document" in capsys.readouterr().err


def test_a_connect_failure_with_no_remote_route_is_still_no_document(cli, store, capsys) -> None:
    code = _sweep_cli(cli, store, _no_document(GUARD_TRACEBACK))

    assert code == 1
    assert "printed no JSON document (exit 1)" in capsys.readouterr().err


def test_a_connect_failure_with_no_document_and_a_failed_fallback_names_both(
    cli, store, capsys, tmp_path
) -> None:
    remote = _railway(tmp_path, FileNotFoundError("railway"))

    code = _sweep_routes(cli, store, FakeProducer(_no_document(GUARD_TRACEBACK)), remote)

    err = capsys.readouterr().err
    assert code == 1
    assert "local: OperationalError at connect" in err
    assert "railway CLI not found" in err


@pytest.mark.parametrize("remote_answers", [True, False], ids=["fallback-ok", "fallback-fails"])
def test_nothing_url_like_from_stderr_reaches_the_output(
    cli, store, capsys, tmp_path, remote_answers
) -> None:
    remote = (
        _railway(tmp_path, _railway_stdout(_doc("no_rows")), returncode=2)
        if remote_answers
        else _railway(tmp_path, RAILWAY_NOISE_BEFORE, returncode=1)
    )

    _sweep_routes(cli, store, FakeProducer(_no_document(GUARD_TRACEBACK)), remote)

    printed = "".join(capsys.readouterr())
    for secret in ("hunter2secret", "postgresql://", "neon.tech", "sqlalche.me", "203.0.113.9"):
        assert secret not in printed


def test_stderr_is_reduced_to_exception_names() -> None:
    names = error_names(GUARD_TRACEBACK)

    assert names == frozenset({"psycopg.OperationalError", "sqlalchemy.exc.OperationalError"})


def test_the_local_producer_reads_its_stderr_for_error_names(tmp_path) -> None:
    def fake_run(argv, **kwargs):
        return type("P", (), {"returncode": 1, "stdout": "", "stderr": GUARD_TRACEBACK})()

    result = GrantspiderHealthCli(tmp_path, run=fake_run).run()

    assert "sqlalchemy.exc.OperationalError" in result.stderr_errors
    assert "hunter2secret" not in repr(result)
