# ABOUTME: Tests that the ci-red sweep proves its watchdog ran: a run GitHub refused to start reads
# ABOUTME: "could not look" (exit 1), never "0 open"; fixtures copy the 2026-11-27 billing refusal.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oversteward.ci_red.sources import (
    GithubCiRed,
    JobInfo,
    SourceUnavailableError,
    Target,
    WatchRun,
)
from oversteward.ci_red.watchdog import RECENT_PRS, REFUSAL_SECONDS
from oversteward.intake.github import GhError
from tests.ci_red.test_ci_red import (  # noqa: F401 — `store` is a fixture used by name
    FISCUS,
    GIT,
    GS,
    OTHER_SHA,
    SHA,
    UNWATCHED_CI,
    FakeGit,
    FakeSource,
    run_main,
    store,
)

BILLING = (
    "The job was not started because recent account payments have failed or your spending "
    "limit needs to be increased. Please check the 'Billing & plans' section in your settings"
)
STARTED = datetime(2026, 11, 27, 7, 8, 33, tzinfo=UTC)
REFUSED_ID = 45956424130


def run(run_id=REFUSED_ID, conclusion="failure", seconds=5, status="completed",
        started=STARTED) -> WatchRun:
    return WatchRun(run_id, status, conclusion, started, started + timedelta(seconds=seconds))


#: grantspider's ci.yml run 45956424130, attempt 1, as GitHub reported it on 2026-11-27.
REFUSED_JOBS = (
    JobInfo(140363843246, "ci", "failure", 0),
    JobInfo(140363859149, "ci-red-alert", "failure", 0),
    JobInfo(140363860637, "neon-integration", "skipped", 0),
    JobInfo(140363861176, "neon-integration-alert", "skipped", 0),
)
REFUSED_ANNOTATIONS = {(GS.full_name, j.id): (BILLING,) for j in REFUSED_JOBS[:2]}


def refused_source(**kw) -> FakeSource:
    """grantspider's newest PR into staging carries the 2026-11-27 refusal."""
    fields = {
        "watch_runs": {(GS.full_name, SHA): run()},
        "jobs": {(GS.full_name, REFUSED_ID): REFUSED_JOBS},
        "annotations": REFUSED_ANNOTATIONS,
    }
    fields.update(kw)
    return FakeSource(**fields)


def assert_could_not_look(store, capsys, source, *expected, targets=None, git=GIT):
    kwargs = {"targets": targets} if targets is not None else {}
    assert run_main(["sweep"], source, store, git=git, **kwargs) == 1
    captured = capsys.readouterr()
    assert "could not look" in captured.err
    for text in expected:
        assert text in captured.err
    assert "Traceback" not in captured.err
    assert "ci-red sweep —" not in captured.out
    assert "0 ci-red issues open" not in captured.out
    assert not store.pending_path.exists()
    return captured.err


def assert_measured(store, capsys, source, **kw):
    assert run_main(["sweep"], source, store, **kw) == 0
    out = capsys.readouterr().out
    assert "  grantspider: 0 open ci-red, watched" in out
    assert json.loads(store.pending_path.read_text()) == {"open": []}


# --- the 2026-11-27 refusal --------------------------------------------------------


def test_a_billing_refused_run_is_could_not_look_with_its_run_id(store, capsys):
    err = assert_could_not_look(
        store, capsys, refused_source(),
        "grantspider: could not look — the watchdog never ran on staging",
        f"ci.yml run {REFUSED_ID} (no job ran a step: {BILLING})",
        f"gh run rerun {REFUSED_ID} --repo NathanKrupa/grantspider",
    )
    assert "fiscus" not in err


def test_zero_step_jobs_are_refused_without_the_annotation_or_a_quick_finish(store, capsys):
    source = refused_source(watch_runs={(GS.full_name, SHA): run(seconds=900)}, annotations={})
    assert_could_not_look(store, capsys, source, f"run {REFUSED_ID} (no job ran a step)")


def test_a_run_with_no_jobs_is_refused(store, capsys):
    source = refused_source(jobs={(GS.full_name, REFUSED_ID): ()})
    assert_could_not_look(store, capsys, source, f"run {REFUSED_ID} (the run has no jobs)")


def test_one_job_that_ran_a_step_is_enough_to_have_run(store, capsys):
    jobs = (*REFUSED_JOBS[:1], JobInfo(9, "ci-red-alert", "success", 1))
    source = refused_source(watch_runs={(GS.full_name, SHA): run(seconds=900)},
                            jobs={(GS.full_name, REFUSED_ID): jobs})
    assert_measured(store, capsys, source)


# --- a quick failure carrying the annotation ---------------------------------------

#: A job GitHub refused beside one that ran: only the annotation and the timing show the refusal.
MIXED_JOBS = (JobInfo(1, "ci", "failure", 0), JobInfo(2, "lint", "success", 3))
MIXED_ANNOTATIONS = {(GS.full_name, 1): ("something else", BILLING)}


def mixed_source(seconds=3, conclusion="failure", annotations=None) -> FakeSource:
    return refused_source(
        watch_runs={(GS.full_name, SHA): run(seconds=seconds, conclusion=conclusion)},
        jobs={(GS.full_name, REFUSED_ID): MIXED_JOBS},
        annotations=MIXED_ANNOTATIONS if annotations is None else annotations,
    )


def test_a_quick_failure_with_the_annotation_is_refused(store, capsys):
    assert_could_not_look(store, capsys, mixed_source(),
                          f"run {REFUSED_ID} (failed within {REFUSAL_SECONDS}s: {BILLING})")


def test_the_refusal_window_is_inclusive_and_ends_there(store, capsys):
    assert_could_not_look(store, capsys, mixed_source(seconds=REFUSAL_SECONDS))
    assert_measured(store, capsys, mixed_source(seconds=REFUSAL_SECONDS + 1))


def test_a_quick_run_that_did_not_fail_is_not_refused(store, capsys):
    assert_measured(store, capsys, mixed_source(conclusion="success"))


def test_a_quick_failure_without_the_annotation_is_a_real_red(store, capsys):
    assert_measured(store, capsys, mixed_source(annotations={(GS.full_name, 1): ("boom",)}))


def test_the_annotation_must_lead_the_message(store, capsys):
    quoted = {(GS.full_name, 1): (f"a log line quoting: {BILLING}",)}
    assert_measured(store, capsys, mixed_source(annotations=quoted))


def test_the_annotation_counts_only_on_a_failed_job(store, capsys):
    on_the_passing_job = {(GS.full_name, 2): (BILLING,)}
    assert_measured(store, capsys, mixed_source(annotations=on_the_passing_job))


# --- red and green runs are untouched ----------------------------------------------


def test_a_red_run_that_ran_its_steps_is_left_to_the_alert_job(store, capsys):
    jobs = (JobInfo(1, "ci", "failure", 29), JobInfo(2, "ci-red-alert", "success", 4))
    source = refused_source(watch_runs={(GS.full_name, SHA): run(seconds=900)},
                            jobs={(GS.full_name, REFUSED_ID): jobs}, annotations={})
    assert_measured(store, capsys, source)


def test_a_green_run_is_clean(store, capsys):
    assert_measured(store, capsys, FakeSource())


# --- which run is read ---------------------------------------------------------------


def test_a_pr_whose_run_is_unfinished_or_absent_passes_to_the_next(store, capsys):
    third = "c" * 40
    source = refused_source(
        pr_heads={(GS.full_name, "staging"): (SHA, OTHER_SHA, third)},
        watch_runs={(GS.full_name, SHA): run(9, status="in_progress"),
                    (GS.full_name, OTHER_SHA): None,
                    (GS.full_name, third): run()},
    )
    assert_could_not_look(store, capsys, source, f"run {REFUSED_ID}")
    assert ("run", GS.full_name, "ci.yml", third) in source.watchdog_reads


#: A green run that tested something, started the day after the 2026-11-27 refusal.
GREEN_AFTER = run(701, conclusion="success", seconds=900, started=STARTED + timedelta(days=1))
GREEN_BEFORE = run(699, conclusion="success", seconds=900, started=STARTED - timedelta(days=1))


def test_a_refusal_on_an_older_pr_is_found_behind_a_newer_prs_green_run(store, capsys):
    """The PR listed first had its last run before the refusal; the refusal still decides."""
    source = refused_source(
        pr_heads={(GS.full_name, "staging"): (OTHER_SHA, SHA)},
        watch_runs={(GS.full_name, OTHER_SHA): GREEN_BEFORE, (GS.full_name, SHA): run()},
    )
    assert_could_not_look(store, capsys, source, f"run {REFUSED_ID}")


def test_a_refusal_started_before_a_green_run_is_superseded(store, capsys):
    source = refused_source(
        pr_heads={(GS.full_name, "staging"): (SHA, OTHER_SHA)},
        watch_runs={(GS.full_name, SHA): run(), (GS.full_name, OTHER_SHA): GREEN_AFTER},
    )
    assert_measured(store, capsys, source)


def test_a_run_every_job_of_which_was_skipped_is_passed_over(store, capsys):
    """A skipped run started after a green one; the green run decides, not the skip."""
    skipped = run(702, conclusion="skipped", seconds=2, started=STARTED + timedelta(days=2))
    source = FakeSource(
        pr_heads={(GS.full_name, "staging"): (SHA, OTHER_SHA)},
        watch_runs={(GS.full_name, SHA): skipped, (GS.full_name, OTHER_SHA): GREEN_AFTER},
        jobs={(GS.full_name, 702): (JobInfo(1, "ci", "skipped", 0),)},
    )
    assert_measured(store, capsys, source)
    assert ("jobs", GS.full_name, 702) not in source.watchdog_reads


def test_no_finished_run_on_the_recent_prs_is_could_not_look(store, capsys):
    source = FakeSource(watch_runs={(GS.full_name, SHA): None})
    assert_could_not_look(store, capsys, source,
                          f"no finished ci.yml run on the last {RECENT_PRS} PRs into staging")
    assert ("heads", GS.full_name, "staging", RECENT_PRS) in source.watchdog_reads


def test_no_pr_into_the_trunk_is_could_not_look(store, capsys):
    source = FakeSource(pr_heads={(GS.full_name, "staging"): ()})
    assert_could_not_look(store, capsys, source, "PRs into staging")


# --- which trunks, which repos ----------------------------------------------------

AG = Target("aigranthelper", "NathanKrupa/aigranthelper", Path("/ag"), "staging")
AG_CI = (
    b"jobs:\n  ci-light:\n    runs-on: x\n  ci-red-alert:\n    runs-on: x\n    if: >-\n"
    b"      ${{ !cancelled() && github.event_name == 'pull_request' &&\n"
    b"          (github.base_ref == 'staging' || github.base_ref == 'main') }}\n"
)
AG_GIT = FakeGit({**GIT.blobs, (AG.checkout, "origin/staging"): AG_CI})


def test_every_trunk_the_alert_job_covers_is_read(store, capsys):
    source = FakeSource(
        pr_heads={(AG.full_name, "staging"): (SHA,), (AG.full_name, "main"): (OTHER_SHA,)},
        watch_runs={(AG.full_name, OTHER_SHA): run()},
        jobs={(AG.full_name, REFUSED_ID): REFUSED_JOBS},
    )
    assert_could_not_look(store, capsys, source,
                          "aigranthelper: could not look — the watchdog never ran on main",
                          targets=[AG, FISCUS], git=AG_GIT)


def test_an_unwatched_repo_is_never_read_for_runs(store, capsys):
    source = FakeSource()
    assert run_main(["sweep"], source, store) == 0
    assert "  fiscus: 0 open ci-red, unwatched" in capsys.readouterr().out
    assert [r for r in source.watchdog_reads if r[1] == FISCUS.full_name] == []
    assert ("heads", GS.full_name, "staging", RECENT_PRS) in source.watchdog_reads


def test_an_alert_job_naming_no_trunk_is_could_not_look(store, capsys):
    no_trunk = b"jobs:\n  ci-red-alert:\n    runs-on: x\n    if: ${{ failure() }}\n"
    git = FakeGit({(GS.checkout, "origin/staging"): no_trunk,
                   (FISCUS.checkout, "origin/main"): UNWATCHED_CI})
    assert run_main(["sweep"], FakeSource(), store, git=git) == 1
    assert "ci-red-alert names no github.base_ref trunk" in capsys.readouterr().err


def test_an_unreadable_run_list_fails_the_sweep(store, capsys):
    source = FakeSource(fail={("heads", GS.full_name, "staging")})
    assert run_main(["sweep"], source, store) == 1
    assert "could not read" in capsys.readouterr().err
    assert not store.pending_path.exists()


# --- the gh connector -----------------------------------------------------------------


def _runner(reply, seen):
    def run_json(args):
        seen.append(args)
        return reply
    return run_json


def test_connector_reads_pr_heads_into_a_base():
    seen = []
    rows = [{"number": 2, "headRefOid": SHA}, {"number": 1, "headRefOid": OTHER_SHA}]
    assert GithubCiRed(run_json=_runner(rows, seen)).recent_pr_heads("o/r", "main", 5) == (
        SHA, OTHER_SHA)
    assert seen == [["pr", "list", "--repo", "o/r", "--base", "main", "--state", "all",
                     "--search", "sort:updated-desc",
                     "--limit", "5", "--json", "number,headRefOid"]]
    with pytest.raises(SourceUnavailableError, match="without a head"):
        GithubCiRed(run_json=_runner([{"number": 2}], [])).recent_pr_heads("o/r", "main", 5)


def test_connector_reads_the_newest_pull_request_run_on_a_head():
    seen = []
    row = {"id": 5, "status": "completed", "conclusion": "failure",
           "run_started_at": "2026-11-27T07:08:33Z", "updated_at": "2026-11-27T07:08:38Z"}
    got = GithubCiRed(run_json=_runner({"workflow_runs": [row]}, seen)).newest_run(
        "o/r", "ci.yml", SHA)
    assert got == run(5)
    assert seen == [["api", f"repos/o/r/actions/workflows/ci.yml/runs?head_sha={SHA}"
                     "&event=pull_request&per_page=1"]]
    empty = GithubCiRed(run_json=_runner({"workflow_runs": []}, []))
    assert empty.newest_run("o/r", "ci.yml", SHA) is None
    bad = GithubCiRed(run_json=_runner({"workflow_runs": [{**row, "updated_at": "soon"}]}, []))
    with pytest.raises(SourceUnavailableError, match="unreadable timestamp"):
        bad.newest_run("o/r", "ci.yml", SHA)
    naive = GithubCiRed(run_json=_runner(
        {"workflow_runs": [{**row, "updated_at": "2026-11-27T07:08:38"}]}, []))
    with pytest.raises(SourceUnavailableError, match="names no zone"):
        naive.newest_run("o/r", "ci.yml", SHA)


def test_connector_reads_every_job_or_refuses():
    seen = []
    reply = {"total_count": 2, "jobs": [
        {"id": 1, "name": "ci", "conclusion": "failure", "steps": []},
        {"id": 2, "name": "lint", "conclusion": "success", "steps": [{}, {}]},
    ]}
    assert GithubCiRed(run_json=_runner(reply, seen)).run_jobs("o/r", 9) == (
        JobInfo(1, "ci", "failure", 0), JobInfo(2, "lint", "success", 2))
    assert seen == [["api", "repos/o/r/actions/runs/9/jobs?per_page=100"]]
    short = {**reply, "total_count": 3}
    with pytest.raises(SourceUnavailableError, match="not all on one page"):
        GithubCiRed(run_json=_runner(short, [])).run_jobs("o/r", 9)
    no_steps = {"total_count": 1, "jobs": [{"id": 1, "name": "ci"}]}
    with pytest.raises(SourceUnavailableError, match="no steps array"):
        GithubCiRed(run_json=_runner(no_steps, [])).run_jobs("o/r", 9)


def test_connector_reads_a_jobs_annotations():
    seen = []
    reply = [{"message": BILLING, "annotation_level": "failure"}]
    assert GithubCiRed(run_json=_runner(reply, seen)).job_annotations("o/r", 7) == (BILLING,)
    assert seen == [["api", "repos/o/r/check-runs/7/annotations?per_page=100"]]
    full = [{"message": "m"}] * 100
    with pytest.raises(SourceUnavailableError, match="annotations unreadable"):
        GithubCiRed(run_json=_runner(full, [])).job_annotations("o/r", 7)


def test_connector_turns_gh_failure_into_unavailable():
    def boom(_args):
        raise GhError("exit 1")

    for call in (lambda g: g.recent_pr_heads("o/r", "main", 5),
                 lambda g: g.newest_run("o/r", "ci.yml", SHA),
                 lambda g: g.run_jobs("o/r", 9),
                 lambda g: g.job_annotations("o/r", 7)):
        with pytest.raises(SourceUnavailableError, match="exit 1"):
            call(GithubCiRed(run_json=boom))
