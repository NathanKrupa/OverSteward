# ABOUTME: Tests for `ci_red.py rerun` — the commit it dispatches on, its refusals, and the guarded
# ABOUTME: delete of its temporary branch. GitHub is a fake; nothing here dispatches a real run.

from __future__ import annotations

import base64
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oversteward.ci_red.rerun import RUN_READS, dispatchable
from oversteward.ci_red.sources import PrInfo, RawIssue, RunInfo, SourceUnavailableError, Target
from oversteward.ci_red.triage import VerdictStore, record
from oversteward.ci_red.workflows import GithubWorkflows
from oversteward.intake.github import GhError

REPO_ROOT = Path(__file__).resolve().parents[2]
AG = Target("aigranthelper", "NathanKrupa/aigranthelper", Path("/ag"), "staging")
TARGETS = [AG]
KEY = "aigranthelper#2847"
TESTED = "a" * 40
MERGE_HEAD = "c" * 40
MOVED = "d" * 40
RED_RUN = 900
NEW_RUN = 1234
WORKFLOW_ID = 77
CI_PATH = ".github/workflows/ci.yml"
BRANCH = "ci-verify-2847"
DISPATCHABLE = b"name: ci\non:\n  pull_request:\n  workflow_dispatch:\njobs: {}\n"
PR_ONLY = b"name: ci\non:\n  pull_request:\njobs: {}\n"


def _load_script():
    spec = importlib.util.spec_from_file_location("ci_red_script", REPO_ROOT / "scripts/ci_red.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def red_issue(body: str | None = None) -> RawIssue:
    if body is None:
        body = (
            f"- Commit tested: `{TESTED}`\n"
            f"- Run: https://github.com/NathanKrupa/aigranthelper/actions/runs/{RED_RUN}\n"
        )
    return RawIssue(
        number=2847,
        title="ci is red on PR #12",
        body=body,
        comments=(),
        state="open",
        labels=frozenset({"ci-red"}),
        created_at="2026-11-11T20:00:00Z",
    )


class FakeSource:
    """The ci-red issue, its red PR and its runs, as `record` and `rerun` read them."""

    def __init__(self, pr: PrInfo, issue: RawIssue | None = None):
        self.raw = issue or red_issue()
        self.pr = pr
        self.runs = {RED_RUN: RunInfo("failure", TESTED, WORKFLOW_ID)}
        self.closed: list[tuple[str, int, str]] = []

    def issue(self, full_name, number):
        return self.raw

    def pr_info(self, full_name, number):
        assert number == 12
        return self.pr

    def run_info(self, full_name, run_id):
        return self.runs[run_id]

    def close(self, full_name, number, comment):
        self.closed.append((full_name, number, comment))


class FakeWorkflows:
    """GitHub's workflows, runs and refs. Every write is logged; the seam tests read the log."""

    def __init__(self, blob=DISPATCHABLE, prior_runs=(), runs_after=None, ref_at_settle="same"):
        self.blob = blob
        self.prior_runs = tuple(prior_runs)
        self.runs_after = runs_after
        self.ref_at_settle = ref_at_settle
        self.refs: dict[str, str] = {}
        self.calls: list[tuple] = []
        self.dispatch_error: Exception | None = None
        self.reads_of_file: list[tuple[str, str]] = []

    def workflow_path(self, full_name, workflow_id):
        assert workflow_id == WORKFLOW_ID
        return CI_PATH

    def file_at(self, full_name, path, sha):
        self.reads_of_file.append((path, sha))
        return self.blob

    def ref_sha(self, full_name, branch):
        if self.dispatched() and self.ref_at_settle != "same":
            return self.ref_at_settle
        return self.refs.get(branch)

    def create_ref(self, full_name, branch, sha):
        self.calls.append(("create_ref", branch, sha))
        self.refs[branch] = sha

    def delete_ref(self, full_name, branch):
        self.calls.append(("delete_ref", branch))
        self.refs.pop(branch)

    def dispatch(self, full_name, workflow_id, branch):
        self.calls.append(("dispatch", workflow_id, branch))
        if self.dispatch_error is not None:
            raise self.dispatch_error

    def dispatched(self) -> bool:
        return any(call[0] == "dispatch" for call in self.calls)

    def dispatched_runs(self, full_name, workflow_id, branch):
        if not self.dispatched():
            return self.prior_runs
        if self.runs_after is not None:
            return self.runs_after
        return (*self.prior_runs, (NEW_RUN, self.refs.get(branch, "")))

    def writes(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def store(tmp_path) -> VerdictStore:
    swept = VerdictStore(tmp_path / "ledger.jsonl", tmp_path / "pending.json")
    swept.save_pending([KEY])
    return swept


def merged(head=MERGE_HEAD, commits=(TESTED, MERGE_HEAD)) -> PrInfo:
    return PrInfo("MERGED", "2026-11-11T20:10:00Z", head, tuple(commits))


def run_rerun(source, workflows, store, sleeps=None, targets=TARGETS, key=KEY):
    return script.main(
        ["rerun", key],
        targets_loader=lambda: targets,
        source=source,
        store=store,
        workflows=workflows,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )


# --- the commit a verdict accepts -------------------------------------------------


def test_a_merged_pr_is_rerun_at_its_merge_head_and_fixed_in_place_accepts_the_run(
    store, capsys
):
    source, workflows = FakeSource(merged()), FakeWorkflows()
    assert run_rerun(source, workflows, store) == 0
    assert workflows.calls == [
        ("create_ref", BRANCH, MERGE_HEAD),
        ("dispatch", WORKFLOW_ID, BRANCH),
        ("delete_ref", BRANCH),
    ]
    assert workflows.reads_of_file == [(CI_PATH, MERGE_HEAD)]
    out = capsys.readouterr().out
    assert f"dispatched run {NEW_RUN} of {CI_PATH} on {MERGE_HEAD} via {BRANCH}" in out
    assert f"  {BRANCH}: deleted" in out
    assert f"record {KEY} fixed-in-place --ref {NEW_RUN}" in out

    source.runs[NEW_RUN] = RunInfo("success", MERGE_HEAD, WORKFLOW_ID)
    record(store, source, TARGETS, KEY, "fixed-in-place", str(NEW_RUN), datetime.now(UTC))
    assert len(source.closed) == 1


@pytest.mark.parametrize(
    "pr",
    [
        PrInfo("OPEN", None, MERGE_HEAD, (TESTED, MERGE_HEAD)),
        PrInfo("CLOSED", None, MERGE_HEAD, (TESTED, MERGE_HEAD)),
        merged(head=TESTED, commits=(TESTED,)),
        merged(commits=(MERGE_HEAD,)),
    ],
    ids=["open", "closed", "merged-at-the-tested-commit", "merged-head-not-after-tested"],
)
def test_otherwise_the_tested_commit_is_rerun_and_green_accepts_the_run(store, capsys, pr):
    source, workflows = FakeSource(pr), FakeWorkflows()
    assert run_rerun(source, workflows, store) == 0
    assert workflows.calls[0] == ("create_ref", BRANCH, TESTED)
    assert f"record {KEY} green --ref {NEW_RUN}" in capsys.readouterr().out

    source.runs[NEW_RUN] = RunInfo("success", TESTED, WORKFLOW_ID)
    record(store, source, TARGETS, KEY, "green", str(NEW_RUN), datetime.now(UTC))
    assert len(source.closed) == 1


def test_an_issue_naming_no_pr_is_rerun_at_the_tested_commit(store):
    issue = red_issue()
    issue = RawIssue(**{**issue.__dict__, "title": "ci is red on staging"})
    workflows = FakeWorkflows()
    assert run_rerun(FakeSource(merged(), issue), workflows, store) == 0
    assert workflows.calls[0] == ("create_ref", BRANCH, TESTED)


def test_a_stale_run_on_the_branch_is_not_taken_for_the_new_one(store, capsys):
    workflows = FakeWorkflows(prior_runs=[(NEW_RUN + 50, MERGE_HEAD)])
    assert run_rerun(FakeSource(merged()), workflows, store) == 0
    assert f"dispatched run {NEW_RUN} " in capsys.readouterr().out


# --- refusals: nothing written --------------------------------------------------------


def _assert_refused(capsys, workflows, message):
    captured = capsys.readouterr()
    assert message in captured.err
    assert "nothing dispatched" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert workflows.calls == []


@pytest.mark.parametrize(
    "blob",
    [PR_ONLY, b"on: push\njobs: {}\n", b"on: [push, pull_request]\njobs: {}\n"],
    ids=["mapping", "string", "list"],
)
def test_a_workflow_without_workflow_dispatch_is_refused(store, capsys, blob):
    workflows = FakeWorkflows(blob=blob)
    assert run_rerun(FakeSource(merged()), workflows, store) == 1
    _assert_refused(capsys, workflows, f"{CI_PATH} at {MERGE_HEAD} has no workflow_dispatch")


def test_an_issue_not_in_the_last_sweep_is_refused(store, capsys):
    store.save_pending(["aigranthelper#1"])
    workflows = FakeWorkflows()
    assert run_rerun(FakeSource(merged()), workflows, store) == 1
    _assert_refused(capsys, workflows, f"{KEY} was not open in the last sweep")


def test_no_sweep_on_record_is_refused(tmp_path, capsys):
    unswept = VerdictStore(tmp_path / "l.jsonl", tmp_path / "p.json")
    workflows = FakeWorkflows()
    assert run_rerun(FakeSource(merged()), workflows, unswept) == 1
    _assert_refused(capsys, workflows, "no measured sweep on record")


def test_an_issue_without_its_tested_commit_and_run_is_refused(store, capsys):
    workflows = FakeWorkflows()
    source = FakeSource(merged(), red_issue(body="no details"))
    assert run_rerun(source, workflows, store) == 1
    _assert_refused(capsys, workflows, f"{KEY} reports no tested commit and red run")


def test_an_existing_verify_branch_is_refused_and_left_alone(store, capsys):
    workflows = FakeWorkflows()
    workflows.refs[BRANCH] = MOVED
    assert run_rerun(FakeSource(merged()), workflows, store) == 1
    _assert_refused(capsys, workflows, f"branch {BRANCH} already exists at {MOVED}")
    assert workflows.refs == {BRANCH: MOVED}


# --- the temporary branch ---------------------------------------------------------


def test_a_branch_moved_after_the_dispatch_is_left_in_place_and_reported(store, capsys):
    workflows = FakeWorkflows(ref_at_settle=MOVED)
    assert run_rerun(FakeSource(merged()), workflows, store) == 1
    assert "delete_ref" not in workflows.writes()
    assert workflows.refs == {BRANCH: MERGE_HEAD}
    captured = capsys.readouterr()
    assert f"dispatched run {NEW_RUN} " in captured.out
    assert f"{BRANCH} moved to {MOVED}; left in place" in captured.err


def test_a_branch_already_gone_is_done(store, capsys):
    workflows = FakeWorkflows(ref_at_settle=None)
    assert run_rerun(FakeSource(merged()), workflows, store) == 0
    assert "delete_ref" not in workflows.writes()
    assert f"  {BRANCH}: already gone" in capsys.readouterr().out


def test_a_run_that_never_appears_leaves_the_branch_and_exits_1(store, capsys):
    sleeps: list[float] = []
    workflows = FakeWorkflows(runs_after=())
    assert run_rerun(FakeSource(merged()), workflows, store, sleeps=sleeps) == 1
    assert len(sleeps) == RUN_READS
    assert workflows.writes() == ["create_ref", "dispatch"]
    assert f"after {RUN_READS} reads; {BRANCH} left in place" in capsys.readouterr().err


def test_a_failed_dispatch_takes_the_branch_back_down(store, capsys):
    workflows = FakeWorkflows()
    workflows.dispatch_error = SourceUnavailableError("HTTP 422")
    assert run_rerun(FakeSource(merged()), workflows, store) == 1
    assert workflows.writes() == ["create_ref", "dispatch", "delete_ref"]
    assert "the dispatch failed — HTTP 422" in capsys.readouterr().err


def test_no_dispatch_targets_exits_2(store, capsys):
    workflows = FakeWorkflows()
    assert run_rerun(FakeSource(merged()), workflows, store, targets=[]) == 2
    assert workflows.calls == []


def test_dispatchable_reads_yaml_on_as_true():
    assert dispatchable(b"on: workflow_dispatch\n")
    assert dispatchable(b"on: [push, workflow_dispatch]\n")
    assert dispatchable(DISPATCHABLE)
    assert not dispatchable(PR_ONLY)
    assert not dispatchable(b"jobs: {}\n")


# --- the connector ------------------------------------------------------------------


def test_connector_argv_for_every_write():
    seen: list[list[str]] = []
    gh = GithubWorkflows(run=seen.append)
    gh.create_ref("o/r", BRANCH, TESTED)
    gh.dispatch("o/r", WORKFLOW_ID, BRANCH)
    gh.delete_ref("o/r", BRANCH)
    assert seen == [
        ["api", "-X", "POST", "repos/o/r/git/refs", "-f", f"ref=refs/heads/{BRANCH}",
         "-f", f"sha={TESTED}"],
        ["api", "-X", "POST", f"repos/o/r/actions/workflows/{WORKFLOW_ID}/dispatches",
         "-f", f"ref={BRANCH}"],
        ["api", "-X", "DELETE", f"repos/o/r/git/refs/heads/{BRANCH}"],
    ]


def test_connector_reads_a_ref_and_a_404_is_absent():
    gh = GithubWorkflows(run_json=lambda args: {"object": {"sha": TESTED}})
    assert gh.ref_sha("o/r", BRANCH) == TESTED

    def missing(args):
        assert args == ["api", f"repos/o/r/git/ref/heads/{BRANCH}"]
        raise GhError("gh api failed (exit 1): gh: Not Found (HTTP 404)")

    assert GithubWorkflows(run_json=missing).ref_sha("o/r", BRANCH) is None

    def down(args):
        raise GhError("gh api failed (exit 1): HTTP 502")

    with pytest.raises(SourceUnavailableError, match="HTTP 502"):
        GithubWorkflows(run_json=down).ref_sha("o/r", BRANCH)


def test_connector_reads_the_workflow_file_and_its_dispatched_runs():
    content = base64.b64encode(DISPATCHABLE).decode()
    answers = {
        f"repos/o/r/contents/{CI_PATH}?ref={TESTED}": {"content": content, "encoding": "base64"},
        f"repos/o/r/actions/workflows/{WORKFLOW_ID}": {"path": CI_PATH},
        f"repos/o/r/actions/workflows/{WORKFLOW_ID}/runs?branch={BRANCH}"
        "&event=workflow_dispatch&per_page=100": {
            "workflow_runs": [{"id": 5, "head_sha": TESTED}]
        },
    }
    gh = GithubWorkflows(run_json=lambda args: answers[args[1]])
    assert gh.file_at("o/r", CI_PATH, TESTED) == DISPATCHABLE
    assert gh.workflow_path("o/r", WORKFLOW_ID) == CI_PATH
    assert gh.dispatched_runs("o/r", WORKFLOW_ID, BRANCH) == ((5, TESTED),)


def test_connector_refuses_a_full_page_of_runs():
    full = {"workflow_runs": [{"id": n, "head_sha": TESTED} for n in range(100)]}
    with pytest.raises(SourceUnavailableError, match="filled the page"):
        GithubWorkflows(run_json=lambda args: full).dispatched_runs("o/r", 1, BRANCH)


def test_claude_md_names_the_rerun_verb():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    sweep_entry = next(line for line in text.splitlines() if line.startswith("- **CI red**"))
    assert "ci_red.py rerun <repo>#<n>" in sweep_entry


def test_the_ledger_is_untouched_by_a_rerun(store):
    assert run_rerun(FakeSource(merged()), FakeWorkflows(), store) == 0
    assert not store.ledger_path.exists()
    assert json.loads(store.pending_path.read_text()) == {"open": [KEY]}
