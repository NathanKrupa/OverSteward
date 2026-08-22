# ABOUTME: Tests for the AG ops triage service, its rendering, and scripts/ag_ops_triage.py's exit codes.
# ABOUTME: The client is injected, so nothing here reaches aigranthelper and no token is needed.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from oversteward.ag_ops.client import AgOpsConfigError
from oversteward.ag_ops.render import QUEUES_CURRENT, render_sweep
from oversteward.ag_ops.triage import (
    ContractDriftError,
    VerdictError,
    VerdictRequest,
    parse_verdict,
    record,
    sweep,
)

from .fakes import (
    CORRECTION_ID,
    CORRECTIONS_QUEUE,
    FEEDBACK_ID,
    FEEDBACK_QUEUE,
    KPI_OVERVIEW,
    UNCONFIGURED_MESSAGE,
    FakeSeam,
    blind_seam,
    busy_seam,
    clean_seam,
    computed_envelope,
    default_reports,
    edge_blocked_seam,
    manifest,
    queue_envelope,
    recorded_result,
    refused_result,
    unconfigured_seam,
    unmounted_seam,
    verdict_envelope,
    waiting_reports,
)

SWEEP = ["sweep"]
RESPOND = f"feedback:{FEEDBACK_ID}:responded"
REJECT = f"correction:{CORRECTION_ID}:rejected"
COULD_NOT_LOOK = "could not look"
DRIFT = "contract drift"


def _load_cli():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "ag_ops_triage.py"
    spec = importlib.util.spec_from_file_location("oversteward_ag_ops_triage_cli", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


# --- sweep: the measured answer ---------------------------------------------


def test_a_sweep_pulls_every_report_the_manifest_names() -> None:
    seam = clean_seam()

    result = sweep(seam)

    assert seam.requested == [FEEDBACK_QUEUE, CORRECTIONS_QUEUE, KPI_OVERVIEW]
    assert [report.name for report in result.reports] == seam.requested


def test_a_sweep_with_items_waiting_counts_only_queue_rows() -> None:
    result = sweep(busy_seam())

    assert result.total_waiting == 2
    assert not result.is_clean


def test_an_empty_seam_is_clean_but_still_carries_its_scanned_counts() -> None:
    result = sweep(clean_seam())

    assert result.is_clean
    assert [report.scanned for report in result.reports] == [0, 0, 2]


def test_a_capped_page_is_reported_incomplete() -> None:
    reports = default_reports()
    reports[FEEDBACK_QUEUE] = queue_envelope(FEEDBACK_QUEUE, [], scanned=91, complete=False)

    result = sweep(FakeSeam(reports=reports))

    assert result.reports[0].scanned == 91
    assert not result.reports[0].complete


# --- the contract tripwire ---------------------------------------------------


def test_a_foreign_contract_major_is_drift_naming_the_version() -> None:
    envelope = manifest()
    envelope["contract_version"] = 2

    with pytest.raises(ContractDriftError, match="contract_version 2"):
        sweep(FakeSeam(manifest_envelope=envelope))


def test_a_manifest_missing_an_envelope_key_is_drift_naming_the_key() -> None:
    with pytest.raises(ContractDriftError, match="reports"):
        sweep(FakeSeam(manifest_envelope={"contract_version": 1}))


def test_a_report_missing_an_envelope_key_is_drift_naming_the_report() -> None:
    reports = default_reports()
    del reports[FEEDBACK_QUEUE]["scanned"]

    with pytest.raises(ContractDriftError, match="scanned"):
        sweep(FakeSeam(reports=reports))


def test_a_report_carrying_neither_items_nor_body_is_drift() -> None:
    reports = default_reports()
    del reports[KPI_OVERVIEW]["body"]

    with pytest.raises(ContractDriftError, match="neither"):
        sweep(FakeSeam(reports=reports))


def test_a_report_carrying_both_items_and_body_is_drift() -> None:
    reports = default_reports()
    reports[KPI_OVERVIEW] = computed_envelope(KPI_OVERVIEW, {"users": 1})
    reports[KPI_OVERVIEW]["items"] = []

    with pytest.raises(ContractDriftError, match="both"):
        sweep(FakeSeam(reports=reports))


def test_an_unversionable_contract_value_is_drift() -> None:
    envelope = manifest()
    envelope["contract_version"] = "unversioned"

    with pytest.raises(ContractDriftError, match="not a version number"):
        sweep(FakeSeam(manifest_envelope=envelope))


def test_a_manifest_promising_a_report_the_producer_404s_is_drift() -> None:
    reports = default_reports()
    del reports[CORRECTIONS_QUEUE]

    with pytest.raises(ContractDriftError, match="registry drift"):
        sweep(FakeSeam(reports=reports))


def test_a_manifest_entry_without_a_name_is_drift() -> None:
    with pytest.raises(ContractDriftError, match="name"):
        sweep(FakeSeam(manifest_envelope=manifest(entries=[{"description": "nameless"}])))


def test_a_verdict_envelope_missing_its_counts_is_drift() -> None:
    seam = FakeSeam(verdicts={"contract_version": 1, "results": []})

    with pytest.raises(ContractDriftError, match="recorded"):
        record(seam, [parse_verdict(RESPOND)])


# --- render: a clean sweep names what it scanned -----------------------------


def test_a_clean_sweep_names_the_scanned_count_of_every_report() -> None:
    text = render_sweep(sweep(clean_seam()))

    assert QUEUES_CURRENT in text
    for name in (FEEDBACK_QUEUE, CORRECTIONS_QUEUE, KPI_OVERVIEW):
        assert name in text
    assert text.count("scanned") == 3


def test_a_clean_sweep_is_never_a_bare_ok() -> None:
    text = render_sweep(sweep(clean_seam()))

    assert "scanned 0 row(s)" in text
    assert "scanned 2 measurement(s)" in text
    assert text.strip() != "ok"


def test_a_capped_page_says_so_in_the_report() -> None:
    reports = default_reports()
    reports[FEEDBACK_QUEUE] = queue_envelope(FEEDBACK_QUEUE, [], scanned=91, complete=False)

    text = render_sweep(sweep(FakeSeam(reports=reports)))

    assert "PAGE CAPPED" in text


def test_a_busy_sweep_lists_every_waiting_row_with_its_id() -> None:
    text = render_sweep(sweep(busy_seam()))

    assert FEEDBACK_ID in text
    assert CORRECTION_ID in text
    assert "Deadline sort is backwards" in text
    assert "responded" in text


# --- record: the write side --------------------------------------------------


def test_record_posts_the_producers_batch_shape() -> None:
    seam = clean_seam()

    record(seam, [parse_verdict(RESPOND), parse_verdict(REJECT)])

    assert seam.posted == [
        [
            {"kind": "feedback", "id": FEEDBACK_ID, "status": "responded"},
            {"kind": "correction", "id": CORRECTION_ID, "status": "rejected"},
        ]
    ]


def test_record_returns_every_per_item_answer() -> None:
    results = [
        recorded_result("feedback", FEEDBACK_ID, "responded"),
        refused_result("correction", CORRECTION_ID, "reviewed", "no such correction"),
    ]
    seam = FakeSeam(verdicts=verdict_envelope(results))

    outcome = record(seam, [parse_verdict(RESPOND), parse_verdict(f"correction:{CORRECTION_ID}:reviewed")])

    assert outcome.recorded == 1
    assert outcome.failed == 1
    assert not outcome.all_ok


def test_a_status_this_token_cannot_reach_is_refused_before_any_call() -> None:
    seam = clean_seam()

    with pytest.raises(VerdictError, match="GrantSpider"):
        record(seam, [VerdictRequest("correction", CORRECTION_ID, "applied")])
    assert seam.posted == []


def test_the_other_grantspider_owned_status_is_refused_too() -> None:
    with pytest.raises(VerdictError, match="GrantSpider"):
        record(clean_seam(), [VerdictRequest("correction", CORRECTION_ID, "gs_dismissed")])


def test_an_unknown_kind_is_refused_before_any_call() -> None:
    seam = clean_seam()

    with pytest.raises(VerdictError, match="unknown kind"):
        record(seam, [VerdictRequest("grant", FEEDBACK_ID, "responded")])
    assert seam.posted == []


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(VerdictError, match="no verdicts"):
        record(clean_seam(), [])


@pytest.mark.parametrize("spec", ["feedback:only-two", "feedback::responded", "a:b:c:d"])
def test_a_malformed_verdict_spec_is_refused(spec: str) -> None:
    with pytest.raises(VerdictError, match="triple"):
        parse_verdict(spec)


# --- the CLI's exit-code contract --------------------------------------------


def test_a_clean_sweep_exits_zero_and_prints_its_counts(cli, capsys) -> None:
    code = cli.main(SWEEP, client_factory=clean_seam)

    out = capsys.readouterr().out
    assert code == 0
    assert QUEUES_CURRENT in out
    assert out.count("scanned") == 3


def test_a_sweep_with_a_queue_exits_zero_and_lists_it(cli, capsys) -> None:
    code = cli.main(SWEEP, client_factory=busy_seam)

    out = capsys.readouterr().out
    assert code == 0
    assert FEEDBACK_ID in out
    assert QUEUES_CURRENT not in out


def test_an_unreadable_seam_exits_one_and_says_it_could_not_look(cli, capsys) -> None:
    code = cli.main(SWEEP, client_factory=blind_seam)

    err = capsys.readouterr().err
    assert code == 1
    assert COULD_NOT_LOOK in err
    assert QUEUES_CURRENT not in err


def test_an_unconfigured_producer_exits_two(cli, capsys) -> None:
    code = cli.main(SWEEP, client_factory=unconfigured_seam)

    assert code == 2
    assert UNCONFIGURED_MESSAGE in capsys.readouterr().err


def test_an_edge_blocked_sweep_exits_one_and_never_blames_the_token(cli, capsys) -> None:
    """OS#394: a CDN 403 sent the operator to rotate a token that was never checked."""
    code = cli.main(SWEEP, client_factory=edge_blocked_seam)

    err = capsys.readouterr().err
    assert code == 1
    assert COULD_NOT_LOOK in err
    assert "edge" in err
    assert "token" not in err


def test_a_missing_token_here_exits_two(cli, capsys) -> None:
    def factory():
        raise AgOpsConfigError("OPS_REPORTS_TOKEN is not set")

    code = cli.main(SWEEP, client_factory=factory)

    assert code == 2
    assert "OPS_REPORTS_TOKEN" in capsys.readouterr().err


def test_a_surface_that_is_not_mounted_exits_two(cli, capsys) -> None:
    code = cli.main(SWEEP, client_factory=unmounted_seam)

    assert code == 2
    assert "not mounted" in capsys.readouterr().err


def test_contract_drift_exits_one_naming_the_drift(cli, capsys) -> None:
    drifted = manifest()
    drifted["contract_version"] = 99

    code = cli.main(SWEEP, client_factory=lambda: FakeSeam(manifest_envelope=drifted))

    err = capsys.readouterr().err
    assert code == 1
    assert DRIFT in err
    assert "99" in err


def test_record_exits_zero_and_prints_each_answer(cli, capsys) -> None:
    code = cli.main(["record", "--verdict", RESPOND], client_factory=clean_seam)

    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out
    assert FEEDBACK_ID in out
    assert "recorded 1, failed 0" in out


def test_record_is_idempotent_on_retry(cli, capsys) -> None:
    """The producer's state machine no-ops a row already at target, so a repeat is safe."""
    first = cli.main(["record", "--verdict", RESPOND], client_factory=clean_seam)
    first_out = capsys.readouterr().out
    second = cli.main(["record", "--verdict", RESPOND], client_factory=clean_seam)
    second_out = capsys.readouterr().out

    assert (first, second) == (0, 0)
    assert first_out == second_out


def test_a_refused_item_is_printed_and_exits_two(cli, capsys) -> None:
    results = [refused_result("correction", CORRECTION_ID, "reviewed", "no such correction")]
    seam = FakeSeam(verdicts=verdict_envelope(results))

    code = cli.main(["record", "--verdict", f"correction:{CORRECTION_ID}:reviewed"], client_factory=lambda: seam)

    out = capsys.readouterr().out
    assert code == 2
    assert "REFUSED" in out
    assert "no such correction" in out


def test_a_verdict_this_token_cannot_set_exits_two_without_calling(cli, capsys) -> None:
    seam = clean_seam()

    code = cli.main(["record", "--verdict", f"correction:{CORRECTION_ID}:applied"], client_factory=lambda: seam)

    assert code == 2
    assert seam.posted == []
    assert "GrantSpider" in capsys.readouterr().err


def test_an_unwritable_store_exits_one(cli, capsys) -> None:
    code = cli.main(["record", "--verdict", RESPOND], client_factory=blind_seam)

    assert code == 1
    assert "could not record" in capsys.readouterr().err


def test_the_waiting_fixture_matches_the_producers_row_shape() -> None:
    """The fixtures are transcriptions of apps/feedback/queues.py — keep them honest."""
    row = waiting_reports()[FEEDBACK_QUEUE]["items"][0]

    assert set(row) == {
        "id",
        "created_at",
        "subject",
        "body",
        "category",
        "status",
        "page_url",
        "from_beta_org",
        "organization_id",
    }
