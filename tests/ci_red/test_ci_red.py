# ABOUTME: Tests for the ci-red sweep — exit codes, watch state, verdict verification, ledger lapse.
# ABOUTME: GitHub and git are injected fakes; nothing here reaches the network or a real checkout.

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oversteward.ci_red.sources import (
    GithubCiRed,
    RawIssue,
    RunInfo,
    SourceUnavailableError,
    Target,
    targets_from_registry,
    watched,
)
from oversteward.ci_red.triage import (
    CiRedUnreadable,
    Ruling,
    VerdictError,
    VerdictStore,
    ci_red_issue,
    read_estate,
    record,
    sweep,
)
from oversteward.intake.github import GhError
from oversteward.intake.line import PROMOTE_OVERRIDE_PREFIX

REPO_ROOT = Path(__file__).resolve().parents[2]
WHEN = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
SHA = "a" * 40
OTHER_SHA = "b" * 40
CI_WORKFLOW_ID = 77

GS = Target("grantspider", "NathanKrupa/grantspider", Path("/gs"), "staging")
FISCUS = Target("fiscus", "NathanKrupa/fiscus", Path("/fiscus"), "main")
TARGETS = [GS, FISCUS]

WATCHED_CI = b"name: ci\njobs:\n  ci:\n    runs-on: x\n  ci-red-alert:\n    runs-on: x\n"
UNWATCHED_CI = b"name: ci\njobs:\n  ci:\n    runs-on: x\n"


def _load_script():
    spec = importlib.util.spec_from_file_location("ci_red_script", REPO_ROOT / "scripts/ci_red.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def details(sha: str = SHA, run: int = 900) -> str:
    """One details block, as grantspider's ci_red_alert.py writes it."""
    return (
        "The `ci` job was red on PR #12: t\n\n"
        "- PR: https://github.com/NathanKrupa/grantspider/pull/12\n"
        f"- Commit tested: `{sha}`\n"
        "- `ci`: failure\n"
        f"- Run: https://github.com/NathanKrupa/grantspider/actions/runs/{run}\n\n"
    )


def red_issue(number: int = 5, comments: tuple[str, ...] = (), **kw) -> RawIssue:
    fields = {
        "number": number,
        "title": "ci is red on PR #12",
        "body": "Capability: gs.dev-gates\n\n" + details(),
        "comments": comments,
        "state": "open",
        "labels": frozenset({"ci-red", "agent-finding"}),
    }
    fields.update(kw)
    return RawIssue(**fields)


class FakeSource:
    """GitHub, as the sweep sees it. Every close is recorded; any read can be made to fail."""

    def __init__(self, open_issues=None, prs=None, runs=None, issue_states=None, fail=()):
        self.open_issues = open_issues or {}
        self.prs = prs or {}
        self.runs = runs or {}
        self.issue_states = issue_states or {}
        self.fail = set(fail)
        self.closed: list[tuple[str, int, str]] = []

    def _check(self, what):
        if what in self.fail:
            raise SourceUnavailableError(f"{what} unreadable")

    def open_ci_red(self, full_name):
        self._check(full_name)
        return tuple(self.open_issues.get(full_name, ()))

    def issue(self, full_name, number):
        self._check(("issue", full_name, number))
        for raw in self.open_issues.get(full_name, ()):
            if raw.number == number:
                return raw
        return red_issue(number, state="closed")

    def issue_state(self, full_name, number):
        self._check(("state", full_name, number))
        return self.issue_states[(full_name, number)]

    def pr_state(self, full_name, number):
        self._check(("pr", full_name, number))
        return self.prs[(full_name, number)]

    def run_info(self, full_name, run_id):
        self._check(("run", full_name, run_id))
        return self.runs[(full_name, run_id)]

    def close(self, full_name, number, comment):
        self._check("close")
        self.closed.append((full_name, number, comment))


class FakeGit:
    def __init__(self, blobs, refs=None):
        self.blobs = blobs
        self.refs = refs

    def __call__(self, root: Path) -> FakeGit:
        self.root = root
        return self

    def has_ref(self, ref):
        return (self.root, ref) in self.refs if self.refs is not None else True

    def blob(self, ref, relpath):
        assert relpath == ".github/workflows/ci.yml"
        return self.blobs.get((self.root, ref))


GIT = FakeGit(
    {(GS.checkout, "origin/staging"): WATCHED_CI, (FISCUS.checkout, "origin/main"): UNWATCHED_CI}
)


@pytest.fixture
def store(tmp_path) -> VerdictStore:
    return VerdictStore(tmp_path / "ledger.jsonl", tmp_path / "pending.json")


def run_main(argv, source, store, git=GIT, targets=TARGETS):
    return script.main(argv, targets_loader=lambda: targets, source=source,
                       repo_factory=git, store=store)


# --- sweep: exit codes and watch state ------------------------------------------


def test_zero_open_prints_watched_and_unwatched_per_repo(store, capsys):
    assert run_main(["sweep"], FakeSource(), store) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "ci-red sweep — 0 ci-red issues open across 2 repos checked"
    assert "  grantspider: 0 open ci-red, watched" in out
    assert "  fiscus: 0 open ci-red, unwatched" in out
    assert json.loads(store.pending_path.read_text()) == {"open": []}


def test_absent_workflow_is_unwatched_but_absent_ref_is_unreadable(store, capsys):
    no_file = FakeGit({(GS.checkout, "origin/staging"): WATCHED_CI})
    assert run_main(["sweep"], FakeSource(), store, git=no_file) == 0
    assert "  fiscus: 0 open ci-red, unwatched" in capsys.readouterr().out

    no_ref = FakeGit(GIT.blobs, refs={(GS.checkout, "origin/staging")})
    assert run_main(["sweep"], FakeSource(), store, git=no_ref) == 1
    captured = capsys.readouterr()
    assert "fiscus: origin/main is not a ref" in captured.err
    assert "ci-red sweep —" not in captured.out


def test_unreadable_repo_exits_1_and_writes_nothing(store, capsys):
    store.pending_path.write_text('{"open": ["grantspider#1"]}\n')
    store.append(Ruling("grantspider#1", "known", "grantspider#2", "t"))
    before = (store.pending_path.read_bytes(), store.ledger_path.read_bytes())
    source = FakeSource(fail={FISCUS.full_name})
    assert run_main(["sweep"], source, store) == 1
    captured = capsys.readouterr()
    assert "could not read — fiscus: NathanKrupa/fiscus unreadable" in captured.err
    assert "ci-red sweep —" not in captured.out
    assert (store.pending_path.read_bytes(), store.ledger_path.read_bytes()) == before


def test_no_dispatch_targets_exits_2(store, capsys):
    assert run_main(["sweep"], FakeSource(), store, targets=[]) == 2
    assert "names no dispatch target" in capsys.readouterr().err
    assert not store.pending_path.exists()


def test_open_issue_is_queued_with_its_override_count(store, capsys):
    comments = (
        "LINE OVERRIDE: dispatching grantspider#4 — flake",
        "PROMOTE OVERRIDE: staging→main — hotfix",
        "a comment that mentions LINE OVERRIDE: in passing",
    )
    source = FakeSource({GS.full_name: [red_issue(5, comments)]})
    assert run_main(["sweep"], source, store) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "ci-red sweep — 1 ci-red issue open across 2 repos checked"
    assert "  grantspider: 1 open ci-red, watched" in out
    assert "  grantspider#5 — ci is red on PR #12 — 2 overrides" in out
    assert json.loads(store.pending_path.read_text()) == {"open": ["grantspider#5"]}


# --- sweep: lapse of a tracking ruling --------------------------------------------


def _readings(source):
    return read_estate(TARGETS, source, lambda t: t is GS)


def test_known_whose_ref_is_closed_is_requeued(store):
    store.append(Ruling("grantspider#5", "known", "grantspider#40", "t"))
    source = FakeSource({GS.full_name: [red_issue(5)]},
                        issue_states={(GS.full_name, 40): "closed"})
    result = sweep(_readings(source), store, source, TARGETS)
    assert [q.issue.key for q in result.queue] == ["grantspider#5"]
    assert result.queue[0].reason == "ruled known → grantspider#40, and grantspider#40 is closed"
    assert result.tracked == ()


def test_known_whose_ref_is_open_stays_tracked(store):
    store.append(Ruling("grantspider#5", "known", "grantspider#40", "t"))
    source = FakeSource({GS.full_name: [red_issue(5)]}, issue_states={(GS.full_name, 40): "open"})
    result = sweep(_readings(source), store, source, TARGETS)
    assert result.queue == ()
    assert [t.issue.key for t in result.tracked] == ["grantspider#5"]


def test_a_tracking_ref_that_cannot_be_read_fails_the_sweep(store, capsys):
    store.append(Ruling("grantspider#5", "filed", "grantspider#40", "t"))
    source = FakeSource({GS.full_name: [red_issue(5)]}, fail={("state", GS.full_name, 40)})
    assert run_main(["sweep"], source, store) == 1
    assert not store.pending_path.exists()
    assert "could not read" in capsys.readouterr().err


def test_closing_ruling_on_a_still_open_issue_is_requeued(store):
    store.append(Ruling("grantspider#5", "fixed", "grantspider#13", "t"))
    source = FakeSource({GS.full_name: [red_issue(5)]})
    result = sweep(_readings(source), store, source, TARGETS)
    assert result.queue[0].reason == "ruled fixed → grantspider#13, yet the issue is open"


# --- record: closing verdicts verify before they close ---------------------------


def _pending(store, *keys):
    store.save_pending(keys or ("grantspider#5",))


def _record(store, source, verdict, ref, key="grantspider#5"):
    return record(store, source, TARGETS, key, verdict, ref, WHEN)


def test_fixed_with_an_open_pr_refuses_and_closes_nothing(store, capsys):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]}, prs={(GS.full_name, 13): "OPEN"})
    with pytest.raises(VerdictError, match="grantspider#13 is OPEN, not MERGED"):
        _record(store, source, "fixed", "grantspider#13")
    assert source.closed == []
    assert not store.ledger_path.exists()
    argv = ["record", "grantspider#5", "fixed", "--ref", "grantspider#13"]
    assert run_main(argv, source, store) == 2
    assert "nothing closed" in capsys.readouterr().err
    assert source.closed == []


def test_fixed_with_a_merged_pr_closes_then_records(store):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]}, prs={(GS.full_name, 13): "MERGED"})
    ruling = _record(store, source, "fixed", "grantspider#13")
    assert source.closed == [
        (GS.full_name, 5,
         "Closed by `scripts/ci_red.py record` (fixed): the fix grantspider#13 is merged.")
    ]
    assert store.rulings()["grantspider#5"] == ruling
    assert ruling.ref == "grantspider#13"


def test_a_failed_close_exits_1_and_writes_no_ruling(store, capsys):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]}, prs={(GS.full_name, 13): "MERGED"},
                        fail={"close"})
    argv = ["record", "grantspider#5", "fixed", "--ref", "grantspider#13"]
    assert run_main(argv, source, store) == 1
    assert "could not verify" in capsys.readouterr().err
    assert not store.ledger_path.exists()


def test_green_on_another_sha_refuses(store):
    _pending(store)
    source = FakeSource(
        {GS.full_name: [red_issue(5)]},
        runs={(GS.full_name, 901): RunInfo("success", OTHER_SHA, CI_WORKFLOW_ID),
              (GS.full_name, 900): RunInfo("failure", SHA, CI_WORKFLOW_ID)},
    )
    with pytest.raises(VerdictError, match=f"tested {OTHER_SHA}, not {SHA}"):
        _record(store, source, "green", "901")
    assert source.closed == []


def test_green_from_another_workflow_refuses(store):
    _pending(store)
    source = FakeSource(
        {GS.full_name: [red_issue(5)]},
        runs={(GS.full_name, 901): RunInfo("success", SHA, 1),
              (GS.full_name, 900): RunInfo("failure", SHA, CI_WORKFLOW_ID)},
    )
    with pytest.raises(VerdictError, match="another workflow"):
        _record(store, source, "green", "901")
    assert source.closed == []


def test_green_that_did_not_succeed_refuses(store):
    _pending(store)
    source = FakeSource(
        {GS.full_name: [red_issue(5)]},
        runs={(GS.full_name, 901): RunInfo("failure", SHA, CI_WORKFLOW_ID),
              (GS.full_name, 900): RunInfo("failure", SHA, CI_WORKFLOW_ID)},
    )
    with pytest.raises(VerdictError, match="not success"):
        _record(store, source, "green", "901")
    assert source.closed == []


def test_green_reads_the_latest_tested_commit_from_a_repeat_red(store):
    _pending(store)
    repeat = details(sha=OTHER_SHA, run=950)
    source = FakeSource(
        {GS.full_name: [red_issue(5, comments=(repeat,))]},
        runs={(GS.full_name, 951): RunInfo("success", OTHER_SHA, CI_WORKFLOW_ID),
              (GS.full_name, 950): RunInfo("failure", OTHER_SHA, CI_WORKFLOW_ID)},
    )
    assert _record(store, source, "green", "951").ref == "951"
    assert [c[:2] for c in source.closed] == [(GS.full_name, 5)]


def test_unmerged_closes_only_for_the_red_pr_closed_without_merging(store):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]},
                        prs={(GS.full_name, 12): "MERGED", (GS.full_name, 99): "CLOSED"})
    with pytest.raises(VerdictError, match="names PR #12, not #99"):
        _record(store, source, "unmerged", "99")
    with pytest.raises(VerdictError, match="is MERGED, not CLOSED"):
        _record(store, source, "unmerged", "#12")
    assert source.closed == []
    source.prs[(GS.full_name, 12)] = "CLOSED"
    assert _record(store, source, "unmerged", "12").ref == "grantspider#12"
    assert [c[:2] for c in source.closed] == [(GS.full_name, 5)]


def test_known_needs_an_open_ref_and_closes_nothing(store):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]},
                        issue_states={(GS.full_name, 40): "closed", (GS.full_name, 41): "open"})
    with pytest.raises(VerdictError, match="grantspider#40 is closed"):
        _record(store, source, "known", "grantspider#40")
    assert _record(store, source, "known", "grantspider#41").verdict == "known"
    assert source.closed == []


def test_record_refuses_a_key_the_last_sweep_did_not_see(store):
    _pending(store, "grantspider#6")
    source = FakeSource({GS.full_name: [red_issue(5)]}, prs={(GS.full_name, 13): "MERGED"})
    with pytest.raises(VerdictError, match="was not open in the last sweep"):
        _record(store, source, "fixed", "grantspider#13")
    assert source.closed == []


def test_record_refuses_an_issue_no_longer_open(store):
    _pending(store, "grantspider#7")
    source = FakeSource({GS.full_name: [red_issue(5)]}, prs={(GS.full_name, 13): "MERGED"})
    with pytest.raises(VerdictError, match="grantspider#7 is not an open ci-red issue"):
        _record(store, source, "fixed", "grantspider#13", key="grantspider#7")
    assert source.closed == []


def test_an_unreadable_pr_is_unreadable_not_a_verdict(store):
    _pending(store)
    source = FakeSource({GS.full_name: [red_issue(5)]}, fail={("pr", GS.full_name, 13)})
    with pytest.raises(CiRedUnreadable):
        _record(store, source, "fixed", "grantspider#13")
    assert source.closed == []


# --- parsing, registry and the gh connector --------------------------------------


def test_issue_parse_reads_title_pr_and_latest_details():
    issue = ci_red_issue("grantspider", red_issue(5, comments=(details(OTHER_SHA, 950),)))
    assert (issue.red_pr, issue.tested_sha, issue.red_run) == (12, OTHER_SHA, 950)


def test_targets_from_registry_reads_checkout_and_branch():
    registry = {"contexts": [
        {"id": "grantspider", "repo": "https://github.com/NathanKrupa/grantspider.git",
         "dispatch_target": True, "local_path": "/gs", "branch": "staging"},
        {"id": "other", "repo": "https://github.com/NathanKrupa/other.git"},
    ]}
    assert targets_from_registry(registry) == [GS]
    del registry["contexts"][0]["branch"]
    with pytest.raises(ValueError, match="names no local_path or branch"):
        targets_from_registry(registry)


def test_watched_reads_the_alert_job_from_the_ref():
    assert watched(GS, repo_factory=GIT) is True
    assert watched(FISCUS, repo_factory=GIT) is False
    broken = FakeGit({(GS.checkout, "origin/staging"): b"jobs: [unclosed"})
    with pytest.raises(SourceUnavailableError, match="is not YAML"):
        watched(GS, repo_factory=broken)


def test_github_connector_lists_by_label_and_refuses_a_full_page():
    seen = []

    def run_json(args):
        seen.append(args)
        return [{"number": n, "title": "t", "labels": [{"name": "ci-red"}]} for n in range(200)]

    with pytest.raises(SourceUnavailableError, match="filled the page of 200"):
        GithubCiRed(run_json=run_json).open_ci_red("o/r")
    assert seen[0][:8] == ["issue", "list", "--repo", "o/r", "--label", "ci-red", "--state", "open"]


def test_github_connector_turns_gh_failure_into_unavailable():
    def boom(_args):
        raise GhError("exit 1")

    with pytest.raises(SourceUnavailableError, match="exit 1"):
        GithubCiRed(run_json=boom).pr_state("o/r", 1)
    with pytest.raises(SourceUnavailableError, match="exit 1"):
        GithubCiRed(run=boom).close("o/r", 1, "c")


def test_github_connector_close_argv():
    seen = []
    GithubCiRed(run=seen.append).close("o/r", 5, "why")
    assert seen == [["issue", "close", "5", "--repo", "o/r", "--comment", "why"]]


def test_promote_hook_writes_the_prefix_the_sweep_counts():
    path = REPO_ROOT / "shared/scripts/dev/guard_promote_ci_red.py"
    spec = importlib.util.spec_from_file_location("guard_promote_ci_red_pin", path)
    hook = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = hook
    spec.loader.exec_module(hook)
    assert hook.OVERRIDE_COMMENT.startswith(PROMOTE_OVERRIDE_PREFIX + " ")


def test_claude_md_runs_the_ci_red_sweep_at_session_start():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Session start — the eight sweeps" in text
    section = text.split("## Session start", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash", 1)[1].split("```", 1)[0]
    assert [line for line in block.splitlines() if "ci_red.py" in line] == [
        ".venv/bin/python scripts/ci_red.py sweep            "
        "# what CI turned red, and whether it was resolved"
    ]
    assert len([line for line in block.splitlines() if line.strip()]) == 9
