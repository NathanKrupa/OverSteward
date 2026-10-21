# ABOUTME: Tests for the abandoned-work sweep — each rule's edges, reopen-by-comment, dry-run, and the CLI.
# ABOUTME: GitHub and git are fakes passed in as parameters; writers are spies; ledgers go to tmp paths.

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oversteward.board.client import NotFoundError, TruncatedReadError
from oversteward.board.config import RepoRef
from oversteward.board.models import Issue
from oversteward.shelve import client as shelve_client
from oversteward.shelve.client import (
    Branch,
    Comment,
    GhWriter,
    LinkedIssue,
    OpenPull,
    RepoSnapshot,
    ShelvedItem,
    Thread,
    read_linked_issue,
    read_snapshot,
)
from oversteward.board.client import GhError
from oversteward.shelve.ledger import LedgerEntry, confine, parse
from oversteward.shelve.sweep import (
    MARKER,
    MissingLabelError,
    Plan,
    Survey,
    SweepTarget,
    execute,
    plan,
    render,
    run_entry,
    survey,
    targets_from_registry,
)
from oversteward.shelve.worktrees import Worktree, WorktreeReadError, read_worktrees

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
WP = RepoRef("wphelper", "NathanKrupa/wphelper")
GS = RepoRef("grantspider", "NathanKrupa/grantspider")


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def thread(*comments: tuple[str, datetime], complete: bool = True) -> Thread:
    return Thread(tuple(Comment(body, when) for body, when in comments), complete)


def pull(number: int, idle_days: float, *comments, complete=True, repo=WP) -> OpenPull:
    return OpenPull(
        repo=repo.id, number=number, title=f"PR {number}", url=f"u/{number}", branch=f"feat/b{number}",
        created_at=ago(400), last_commit_at=ago(idle_days), last_review_at=None,
        thread=thread(*comments, complete=complete),
    )


def issue(number: int, idle_days: float, *labels: str, repo=WP) -> Issue:
    return Issue(
        repo=repo.id, number=number, title=f"Issue {number}", url=f"i/{number}", state="OPEN",
        labels=frozenset(labels), created_at=ago(500), updated_at=ago(idle_days), closed_at=None,
        body_refs=frozenset(),
    )


def shelved_item(number: int, closed_days: float, *comments, kind="pr", repo=WP) -> ShelvedItem:
    return ShelvedItem(repo=repo.id, kind=kind, number=number, title=f"Shelved {number}",
                       url=f"s/{number}", closed_at=ago(closed_days), thread=thread(*comments))


def snap(*, pulls=(), issues=(), shelved=(), branches=(), labels=("shelved",), repo=WP):
    return RepoSnapshot(repo=repo, default_branch="main", labels=frozenset(labels),
                        pulls=tuple(pulls), shelved=tuple(shelved), issues=tuple(issues),
                        branches=tuple(branches))


TARGET = SweepTarget(WP, frozenset({"main"}), "main", None)


def decide(snapshot: RepoSnapshot, *, linked=None, trees=(), target=TARGET) -> Plan:
    found = Survey(snapshots={target.repo.id: snapshot}, linked=linked or {}, worktrees=tuple(trees))
    return plan([target], found, NOW)


def verbs(decided: Plan) -> dict[tuple[str, int | str | None], str]:
    return {(a.kind, a.number if a.number is not None else a.ref): a.verb for a in decided.actions}


class SpyWriter:
    def __init__(self, fail_on: str | None = None, error: type[Exception] = RuntimeError):
        self.calls: list[tuple] = []
        self.fail_on = fail_on
        self.error = error

    def _hit(self, name, *args):
        if name == self.fail_on:
            raise self.error("write failed")
        self.calls.append((name, *args))

    def shelve_pull(self, repo, number, comment):
        self._hit("shelve_pull", repo.id, number, comment)

    def close_finding(self, repo, number, comment):
        self._hit("close_finding", repo.id, number, comment)

    def reopen(self, repo, kind, number):
        self._hit("reopen", repo.id, kind, number)

    def note(self, repo, number, comment):
        self._hit("note", repo.id, number, comment)


def run(decided: Plan, *, apply: bool, writer=None):
    """``(entries, recorded actions)``; the run's closing line is checked, then set aside."""
    recorded: list[LedgerEntry] = []
    outcome = execute(decided, apply=apply, writer=writer, record=recorded.extend, now=NOW)
    assert recorded[-1].rule == "sweep-run"
    return outcome.entries, recorded[:-1]


# --- pull requests ---------------------------------------------------------


def test_a_pull_request_idle_twenty_days_stays_open():
    assert verbs(decide(snap(pulls=[pull(1, 20.99)]))) == {}


def test_a_pull_request_idle_twenty_one_days_is_shelved():
    decided = decide(snap(pulls=[pull(1, 21)]))

    assert verbs(decided) == {("pr", 1): "shelve"}
    (action,) = decided.actions
    assert action.comment.startswith("shelved — reopen by comment.")
    assert "`feat/b1` is kept" in action.comment


@pytest.mark.parametrize("age", [21, 60, 400])
def test_a_carried_pull_request_stays_open_at_any_age(age):
    note = ("Carried: waiting on the client's copy", ago(age))
    assert verbs(decide(snap(pulls=[pull(1, age, note)]))) == {}


def test_a_recent_comment_is_motion():
    assert verbs(decide(snap(pulls=[pull(1, 50, ("any news?", ago(3)))]))) == {}


def test_a_pull_request_opened_recently_from_an_old_branch_is_not_idle():
    opened = OpenPull(**{**{f: getattr(pull(1, 50), f) for f in OpenPull.__slots__},
                         "created_at": ago(1)})
    assert verbs(decide(snap(pulls=[opened]))) == {}


def test_a_recent_review_is_motion():
    reviewed = OpenPull(**{**{f: getattr(pull(1, 50), f) for f in OpenPull.__slots__},
                           "last_review_at": ago(2)})
    assert verbs(decide(snap(pulls=[reviewed]))) == {}


def test_the_sweeps_own_comment_is_neither_motion_nor_carried():
    own_comment = (f"shelved — reopen by comment.\ncarried: no\n{MARKER} -->", ago(1))
    assert verbs(decide(snap(pulls=[pull(1, 30, own_comment)]))) == {("pr", 1): "shelve"}


def test_every_comment_the_sweep_writes_carries_its_marker():
    comments = [a.comment for a in _busy_plan().actions if a.comment is not None]

    assert len(comments) == 3
    assert all(MARKER in c for c in comments)


def test_a_shelve_comment_left_on_an_open_pull_is_not_motion():
    comment = decide(snap(pulls=[pull(1, 30)])).actions[0].comment
    stuck = pull(1, 30, (comment, ago(1)))
    assert verbs(decide(snap(pulls=[stuck]))) == {("pr", 1): "shelve"}


def test_a_comment_carrying_the_marker_never_exempts_even_if_it_begins_carried():
    forged = (f"carried: by the sweep itself\n{MARKER} -->", ago(30))
    assert verbs(decide(snap(pulls=[pull(1, 30, forged)]))) == {("pr", 1): "shelve"}


def test_carried_inside_a_sentence_does_not_exempt():
    said = ("this is not carried: really", ago(40))
    assert verbs(decide(snap(pulls=[pull(1, 40, said)]))) == {("pr", 1): "shelve"}


def test_a_cut_thread_is_reported_not_shelved():
    decided = decide(snap(pulls=[pull(1, 40, ("old", ago(40)), complete=False)]))
    assert verbs(decided) == {("pr", 1): "report"}
    assert decided.actions[0].rule == "pr-idle-unjudged"


# --- issues ----------------------------------------------------------------


def test_an_agent_finding_idle_fifty_nine_days_stays_open():
    assert verbs(decide(snap(issues=[issue(5, 59.9, "agent-finding")]))) == {}


def test_an_agent_finding_idle_sixty_days_closes_as_not_planned():
    decided = decide(snap(issues=[issue(5, 60, "agent-finding")]))
    assert verbs(decided) == {("issue", 5): "close"}
    assert decided.actions[0].comment.startswith("shelved — reopen by comment.")


def test_a_two_hundred_day_issue_without_agent_finding_is_never_closed():
    decided = decide(snap(issues=[issue(7, 200, "needs-input")]))
    assert verbs(decided) == {("issue", 7): "candidate"}

    spy = SpyWriter()
    run(decided, apply=True, writer=spy)
    assert spy.calls == []


def test_an_ordinary_issue_becomes_a_candidate_only_at_ninety_days():
    assert verbs(decide(snap(issues=[issue(7, 89.9)]))) == {}
    assert verbs(decide(snap(issues=[issue(7, 90)]))) == {("issue", 7): "candidate"}


# --- reopen by comment -----------------------------------------------------


def test_a_reopen_comment_after_the_shelve_reopens():
    item = shelved_item(3, 10, (f"shelved — reopen by comment.\n{MARKER} -->", ago(10.01)),
                        ("Reopen — the client answered", ago(1)))
    decided = decide(snap(shelved=[item]))
    assert verbs(decided) == {("pr", 3): "reopen"}

    spy = SpyWriter()
    run(decided, apply=True, writer=spy)
    assert spy.calls == [("reopen", "wphelper", "pr", 3)]


def test_the_sweeps_own_comment_never_reopens_even_after_the_close():
    own_comment = (f"reopen\n{MARKER} -->", ago(1))
    assert verbs(decide(snap(shelved=[shelved_item(3, 10, own_comment)]))) == {}


def test_the_sweeps_shelve_comment_does_not_begin_with_reopen():
    comment = decide(snap(pulls=[pull(1, 30)])).actions[0].comment
    item = shelved_item(1, 2, (comment.replace(MARKER, "<!-- x"), ago(1)))
    assert verbs(decide(snap(shelved=[item]))) == {}


@pytest.mark.parametrize("said", ["Reopened as #640 after the rebase; leave this one closed",
                                  "reopening this in the new PR"])
def test_a_comment_about_reopening_elsewhere_does_not_reopen(said):
    assert verbs(decide(snap(shelved=[shelved_item(3, 10, (said, ago(1)))]))) == {}


@pytest.mark.parametrize("said", ["reopen", "Reopen — the client answered", "  REOPEN: back on"])
def test_reopen_as_a_word_at_the_start_reopens(said):
    assert verbs(decide(snap(shelved=[shelved_item(3, 10, (said, ago(1)))]))) == {("pr", 3): "reopen"}


def test_a_reopen_comment_from_before_the_close_does_not_reopen():
    item = shelved_item(3, 10, ("reopen please", ago(11)))
    assert verbs(decide(snap(shelved=[item]))) == {}


def test_only_the_newest_comment_counts():
    item = shelved_item(3, 10, ("reopen", ago(5)), ("never mind, leave it", ago(4)))
    assert verbs(decide(snap(shelved=[item]))) == {}


def test_a_shelved_issue_reopens_through_the_issue_path():
    item = shelved_item(9, 10, ("reopen", ago(1)), kind="issue")
    assert verbs(decide(snap(shelved=[item]))) == {("issue", 9): "reopen"}


# --- branches --------------------------------------------------------------


def branch(name, days, has_pull=False):
    return Branch(repo="wphelper", name=name, last_commit_at=ago(days), has_pull=has_pull)


def test_a_branch_without_a_pull_request_is_reported_at_thirty_days():
    decided = decide(snap(branches=[branch("feat/x", 29.9), branch("feat/y", 30)]))
    assert verbs(decided) == {("branch", "feat/y"): "report"}


def test_a_branch_with_a_pull_request_and_the_trunks_are_never_reported():
    target = SweepTarget(WP, frozenset({"staging", "main"}), "staging", None)
    branches = [branch("feat/x", 90, has_pull=True), branch("main", 90), branch("staging", 90)]
    assert verbs(decide(snap(branches=branches), target=target)) == {}


def test_the_github_default_branch_is_a_trunk_even_when_the_registry_names_another():
    target = SweepTarget(WP, frozenset({"staging"}), "staging", None)
    assert verbs(decide(snap(branches=[branch("main", 90)]), target=target)) == {}


def test_a_cut_linked_thread_is_treated_as_already_noted():
    linked = {("wphelper", 44): LinkedIssue(44, open=True, comment_bodies=(), complete=False)}
    decided = decide(snap(branches=[branch("fix/issue-44-thing", 45)]), linked=linked)
    assert verbs(decided) == {("branch", "fix/issue-44-thing"): "report"}


def test_a_linked_open_issue_gets_one_close_out_note():
    stale = branch("fix/issue-44-thing", 45)
    linked = {("wphelper", 44): LinkedIssue(44, open=True, comment_bodies=("hello",))}
    decided = decide(snap(branches=[stale]), linked=linked)
    assert verbs(decided) == {("branch", "fix/issue-44-thing"): "report", ("issue", 44): "note"}

    noted = LinkedIssue(44, open=True, comment_bodies=(decided.actions[1].comment,))
    again = decide(snap(branches=[stale]), linked={("wphelper", 44): noted})
    assert verbs(again) == {("branch", "fix/issue-44-thing"): "report"}


def test_a_closed_linked_issue_gets_no_note():
    linked = {("wphelper", 44): LinkedIssue(44, open=False, comment_bodies=())}
    decided = decide(snap(branches=[branch("fix/issue-44-thing", 45)]), linked=linked)
    assert verbs(decided) == {("branch", "fix/issue-44-thing"): "report"}


def test_a_dated_branch_name_is_not_read_as_an_issue_link():
    from oversteward.shelve.sweep import linked_issue_number

    assert linked_issue_number("session/dream-promotion-2026-10-08") is None
    assert linked_issue_number("fix/issue-44-thing") == 44


def test_the_branch_is_never_deleted_by_any_write():
    gh = FakeGh()
    writer = GhWriter(run=gh)
    writer.shelve_pull(WP, 1, "c")
    writer.close_finding(WP, 2, "c")
    writer.reopen(WP, "pr", 3)
    writer.note(WP, 4, "c")

    paths = [a[3] for a in gh.calls]
    assert not any("git/refs" in p or "/branches" in p for p in paths)
    deletes = [a for a in gh.calls if a[2] == "DELETE"]
    assert [a[3] for a in deletes] == ["repos/NathanKrupa/wphelper/issues/3/labels/shelved"]


# --- worktrees -------------------------------------------------------------


def tree(path, days, landed=False):
    when = ago(days) if days is not None else None
    return Worktree("wphelper", Path(path), "session/x", when, landed)


def test_an_unlanded_worktree_is_reported_after_a_week_and_a_landed_one_never():
    trees = [tree("/w/a", 6.9), tree("/w/b", 7), tree("/w/c", 90, landed=True), tree("/w/d", None)]
    assert verbs(decide(snap(), trees=trees)) == {
        ("worktree", "/w/b"): "report",
        ("worktree", "/w/d"): "report",
    }


class FakeGit:
    def __init__(self, landed_rc=0):
        self.calls = []
        self.landed_rc = landed_rc

    def __call__(self, args):
        self.calls.append(args)
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        if "log" in args:
            return subprocess.CompletedProcess(args, 0, "2026-09-01T00:00:00+00:00\n", "")
        return subprocess.CompletedProcess(args, self.landed_rc, "", "bad" if self.landed_rc > 1 else "")


def test_read_worktrees_skips_the_primary_and_asks_git_about_landing(tmp_path):
    linked = tmp_path / "wt"
    linked.mkdir()
    gone = tmp_path / "gone"
    checkouts = lambda _p: [(tmp_path, "main"), (linked, "session/a"), (gone, None)]  # noqa: E731

    git = FakeGit(landed_rc=1)
    found = read_worktrees("wphelper", tmp_path, "main", checkouts=checkouts, git=git)

    assert [t.path for t in found] == [linked, gone]
    assert found[0].landed is False and found[1].missing
    assert ["-C", str(tmp_path), "merge-base", "--is-ancestor", "abc123", "origin/main"] in git.calls


def test_read_worktrees_could_not_look_is_an_error_not_landed(tmp_path):
    checkouts = lambda _p: [(tmp_path, "main"), (tmp_path, "x")]  # noqa: E731
    with pytest.raises(WorktreeReadError):
        read_worktrees("wphelper", tmp_path, "main", checkouts=checkouts, git=FakeGit(landed_rc=128))


# --- execution -------------------------------------------------------------


def _busy_plan() -> Plan:
    return decide(snap(
        pulls=[pull(1, 30)],
        issues=[issue(5, 70, "agent-finding"), issue(6, 120)],
        shelved=[shelved_item(3, 10, ("reopen", ago(1)))],
        branches=[branch("fix/issue-44-x", 45)],
    ), linked={("wphelper", 44): LinkedIssue(44, True, ())})


def test_a_dry_run_never_calls_the_writer_and_ledgers_every_action_as_dry():
    decided = _busy_plan()
    spy = SpyWriter()

    entries, recorded = run(decided, apply=False, writer=spy)

    assert spy.calls == []
    assert len(recorded) == len(decided.actions) == 6
    assert {e.mode for e in recorded} == {"dry"}


def test_an_apply_performs_each_write_and_ledgers_it_applied():
    spy = SpyWriter()
    entries, recorded = run(_busy_plan(), apply=True, writer=spy)

    assert [c[0] for c in spy.calls] == ["reopen", "shelve_pull", "close_finding", "note"]
    assert {e.mode for e in recorded} == {"applied"}
    assert len(recorded) == 6


def test_an_apply_without_the_shelved_label_refuses_before_any_write():
    decided = decide(snap(pulls=[pull(1, 30)], labels=()))
    spy = SpyWriter()

    with pytest.raises(MissingLabelError):
        run(decided, apply=True, writer=spy)
    assert spy.calls == []
    assert decided.unlabelled == ("wphelper",)


def test_closing_a_finding_without_the_shelved_label_also_refuses():
    decided = decide(snap(issues=[issue(5, 70, "agent-finding")], labels=("agent-finding",)))
    spy = SpyWriter()

    with pytest.raises(MissingLabelError):
        run(decided, apply=True, writer=spy)
    assert spy.calls == []


def test_an_unexpected_write_error_stops_the_run_with_only_completed_actions_ledgered():
    spy = SpyWriter(fail_on="close_finding")
    recorded: list[LedgerEntry] = []
    with pytest.raises(RuntimeError):
        execute(_busy_plan(), apply=True, writer=spy, record=recorded.extend, now=NOW)
    assert [e.action for e in recorded] == ["reopen", "shelve"]


def test_a_write_github_refuses_is_set_aside_and_the_rest_still_run():
    spy = SpyWriter(fail_on="reopen", error=GhError)
    recorded: list[LedgerEntry] = []

    outcome = execute(_busy_plan(), apply=True, writer=spy, record=recorded.extend, now=NOW)

    assert [c[0] for c in spy.calls] == ["shelve_pull", "close_finding", "note"]
    assert [(f.action.verb, f.action.number) for f in outcome.failures] == [("reopen", 3)]
    assert "reopen" not in [e.action for e in recorded]
    assert recorded[-1].rule == "sweep-run" and recorded[-1].reason == "5 actions"


def test_every_run_closes_with_a_run_line_even_when_it_decided_nothing():
    recorded: list[LedgerEntry] = []
    execute(decide(snap()), apply=False, writer=None, record=recorded.extend, now=NOW)

    (line,) = recorded
    assert (line.kind, line.rule, line.mode, line.reason) == ("run", "sweep-run", "dry", "0 actions")


def test_render_says_would_for_a_dry_run():
    entries, _ = run(_busy_plan(), apply=False)
    text = render(entries, apply=False, unlabelled=("wphelper",))

    assert "DRY RUN" in text
    assert "- would shelve wphelper#1" in text
    assert "- would close wphelper#5" in text
    assert "--apply would refuse" in text
    assert "- shelved " not in text


def test_the_ledger_appends_one_json_line_per_entry(tmp_path):
    entries, _ = run(_busy_plan(), apply=False)
    path = tmp_path / "state" / "ledger.jsonl"
    _module().append_ledger(path, tmp_path, entries[:2])
    _module().append_ledger(path, tmp_path, entries[2:])

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6
    assert rows[0]["mode"] == "dry" and rows[0]["at"] == NOW.isoformat()
    assert parse(path.read_text(encoding="utf-8")) == entries


def test_a_ledger_line_that_does_not_parse_is_an_error_not_a_skip():
    with pytest.raises(ValueError, match="line 2"):
        parse('{"x": 1}\n'.replace('{"x": 1}', run_entry("dry", NOW, 0).to_json()) + "{torn\n")


def test_confine_refuses_a_path_outside_the_state_directory(tmp_path):
    assert confine(tmp_path / "a" / "l.jsonl", tmp_path) == (tmp_path / "a" / "l.jsonl").resolve()
    with pytest.raises(ValueError):
        confine(tmp_path / ".." / "l.jsonl", tmp_path)


# --- GitHub transport ------------------------------------------------------


def _conn(nodes, has_next=False, cursor="c1"):
    return {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}


class FakeGh:
    """Answers gh argv: label/issue lists, GraphQL by connection, REST writes recorded."""

    def __init__(self, pulls_pages=None, labels=("shelved",), issues=(), branches=(),
                 shelved_prs=(), rest=None, issue_total=1):
        self.pulls_pages = list(pulls_pages or [[]])
        self.labels, self.issues, self.branches = labels, issues, branches
        self.shelved_prs = shelved_prs
        self.rest = rest or {}
        self.issue_total = issue_total
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["label", "list"]:
            return [{"name": n} for n in self.labels]
        if args[:2] == ["issue", "list"]:
            return list(self.issues)
        if args[:2] == ["api", "graphql"]:
            query = args[3]
            if "pullRequests(states: OPEN" in query:
                page = self.pulls_pages.pop(0)
                return {"data": {"repository": {"pullRequests": _conn(page, bool(self.pulls_pages))}}}
            if "pullRequests(states: CLOSED" in query:
                return {"data": {"repository": {"pullRequests": _conn(list(self.shelved_prs))}}}
            if "issues(states: CLOSED" in query:
                return {"data": {"repository": {"issues": _conn([])}}}
            if "refs(" in query:
                return {"data": {"repository": {"defaultBranchRef": {"name": "main"},
                                                "refs": _conn(list(self.branches))}}}
            if "issue(number" in query:
                comments = {"totalCount": self.issue_total, "nodes": [{"body": "b"}]}
                return {"data": {"repository": {"issue": {"comments": comments}}}}
        if args[0] == "api":
            key = args[-1] if args[1] != "-X" else args[3]
            if key in self.rest:
                answer = self.rest[key]
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return {}
        raise AssertionError(f"unexpected gh call {args}")


def _pr_node(number, comments=(), total=None):
    return {
        "number": number, "title": "t", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
        "headRefName": "feat/x",
        "commits": {"nodes": [{"commit": {"committedDate": "2026-09-01T00:00:00Z"}}]},
        "reviews": {"nodes": []},
        "comments": {"totalCount": total if total is not None else len(comments),
                     "nodes": [{"body": b, "createdAt": "2026-09-02T00:00:00Z"} for b in comments]},
    }


def test_read_snapshot_pages_open_pulls_and_reads_the_newest_comments():
    gh = FakeGh(pulls_pages=[[_pr_node(1)], [_pr_node(2, ["hi"])]])
    snapshot = read_snapshot(WP, run=gh)

    assert [p.number for p in snapshot.pulls] == [1, 2]
    pull_queries = [c for c in gh.calls if c[:2] == ["api", "graphql"] and "states: OPEN" in c[3]]
    assert "comments(last: 100)" in pull_queries[0][3]
    assert "cursor=c1" in pull_queries[1]
    assert snapshot.pulls[1].last_commit_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_a_thread_longer_than_the_window_reads_as_incomplete():
    snapshot = read_snapshot(WP, run=FakeGh(pulls_pages=[[_pr_node(1, ["a"], total=250)]]))
    assert snapshot.pulls[0].thread.complete is False


def test_the_shelved_read_asks_for_closed_items_with_the_label():
    read_snapshot(WP, run=(gh := FakeGh()))
    closed = [c for c in gh.calls if c[:2] == ["api", "graphql"] and "states: CLOSED" in c[3]]
    assert len(closed) == 2
    assert all("label=shelved" in c for c in closed)


def test_a_connection_that_never_ends_is_refused(monkeypatch):
    monkeypatch.setattr(shelve_client, "MAX_PAGES", 2)
    gh = FakeGh(pulls_pages=[[_pr_node(1)], [_pr_node(2)], [_pr_node(3)]])
    with pytest.raises(TruncatedReadError):
        read_snapshot(WP, run=gh)


def test_read_snapshot_reads_branches_with_their_pull_count():
    node = {"name": "feat/z", "target": {"committedDate": "2026-08-01T00:00:00Z"},
            "associatedPullRequests": {"totalCount": 0}}
    with_pull = {**node, "name": "feat/p", "associatedPullRequests": {"totalCount": 1}}
    snapshot = read_snapshot(WP, run=FakeGh(branches=[node, with_pull]))
    assert snapshot.default_branch == "main"
    assert snapshot.branches == (
        Branch("wphelper", "feat/z", datetime(2026, 8, 1, tzinfo=UTC), False),
        Branch("wphelper", "feat/p", datetime(2026, 8, 1, tzinfo=UTC), True),
    )


def test_a_linked_number_that_is_a_pull_request_or_missing_is_no_issue():
    gh = FakeGh(rest={"repos/NathanKrupa/wphelper/issues/5": {"pull_request": {}, "state": "open"},
                      "repos/NathanKrupa/wphelper/issues/6": NotFoundError("HTTP 404")})
    assert read_linked_issue(WP, 5, run=gh) is None
    assert read_linked_issue(WP, 6, run=gh) is None


def test_a_linked_issue_reads_its_state_and_comments():
    gh = FakeGh(rest={"repos/NathanKrupa/wphelper/issues/7": {"state": "open"},
                      "repos/NathanKrupa/wphelper/issues/8": {"state": "closed"}})
    assert read_linked_issue(WP, 7, run=gh) == LinkedIssue(7, True, ("b",), complete=True)
    assert read_linked_issue(WP, 8, run=gh).open is False


def test_a_linked_issue_with_more_comments_than_read_is_incomplete():
    gh = FakeGh(rest={"repos/NathanKrupa/wphelper/issues/7": {"state": "open"}}, issue_total=250)
    assert read_linked_issue(WP, 7, run=gh).complete is False


def test_the_writer_labels_before_it_closes():
    gh = FakeGh()
    GhWriter(run=gh).shelve_pull(WP, 1, "shelved — reopen by comment.")

    assert [(c[2], c[3]) for c in gh.calls] == [
        ("POST", "repos/NathanKrupa/wphelper/issues/1/labels"),
        ("POST", "repos/NathanKrupa/wphelper/issues/1/comments"),
        ("PATCH", "repos/NathanKrupa/wphelper/pulls/1"),
    ]
    assert gh.calls[-1][-1] == "state=closed"


def test_the_writer_closes_a_finding_as_not_planned_and_reopens_before_unlabelling():
    gh = FakeGh()
    GhWriter(run=gh).close_finding(WP, 2, "c")
    GhWriter(run=gh).reopen(WP, "issue", 2)

    assert gh.calls[2][-2:] == ["-f", "state_reason=not_planned"]
    assert [(c[2], c[3]) for c in gh.calls[3:]] == [
        ("PATCH", "repos/NathanKrupa/wphelper/issues/2"),
        ("DELETE", "repos/NathanKrupa/wphelper/issues/2/labels/shelved"),
    ]


# --- survey and registry ---------------------------------------------------


def test_survey_reads_the_linked_issue_only_for_a_stale_branch():
    stale, fresh = branch("fix/issue-44-a", 45), branch("fix/issue-45-b", 3)
    asked = []

    found = survey(
        [TARGET], now=NOW,
        read_repo=lambda repo: snap(branches=[stale, fresh]),
        read_issue=lambda repo, n: asked.append(n) or LinkedIssue(n, True, ()),
        read_trees=lambda target: (),
    )
    assert asked == [44]
    assert found.linked == {("wphelper", 44): LinkedIssue(44, True, ())}


def test_targets_come_from_dispatch_targets_with_both_trunks():
    registry = {"contexts": [
        {"id": "grantspider", "repo": "https://github.com/NathanKrupa/grantspider.git",
         "branch": "staging", "primary_branch": "main", "local_path": "/home/natha/grantspider",
         "dispatch_target": True},
        {"id": "billions", "repo": "https://github.com/NathanKrupa/billions.git"},
    ]}
    assert targets_from_registry(registry) == [
        SweepTarget(GS, frozenset({"staging", "main"}), "staging", Path("/home/natha/grantspider"))
    ]


# --- CLI -------------------------------------------------------------------


def _module():
    spec = importlib.util.spec_from_file_location("shelve_sweep", REPO_ROOT / "scripts" / "shelve_sweep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REGISTRY = {"contexts": [{"id": "wphelper", "repo": "https://github.com/NathanKrupa/wphelper.git",
                           "branch": "main", "dispatch_target": True}]}


def _main(argv, *, snapshot=None, writers=None, environ=None, state_dir=None):
    writers = writers if writers is not None else []

    def make_writer():
        writers.append(SpyWriter())
        return writers[-1]

    return _module().main(
        argv,
        registry=lambda: _REGISTRY,
        trees=lambda: (lambda target: ()),
        writer=make_writer,
        read_repo=lambda repo: snapshot or snap(pulls=[pull(1, 30)]),
        read_issue=lambda repo, n: None,
        now=lambda: NOW,
        environ=environ or {},
        state_dir=state_dir or Path("/tmp"),
    )


def test_cli_dry_run_is_the_default_and_never_builds_a_writer(tmp_path, capsys):
    ledger = tmp_path / "ledger.jsonl"
    writers: list = []

    assert _main(["--ledger", str(ledger)], writers=writers) == 0
    assert writers == []
    row, closing = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert row["mode"] == "dry" and row["action"] == "shelve"
    assert closing["rule"] == "sweep-run" and closing["mode"] == "dry"
    assert "would shelve wphelper#1" in capsys.readouterr().out


def test_cli_apply_writes_through_the_writer(tmp_path):
    writers: list = []
    assert _main(["--ledger", str(tmp_path / "l.jsonl"), "--apply"], writers=writers) == 0
    assert [c[0] for c in writers[0].calls] == ["shelve_pull"]


def test_cli_exits_one_when_github_refuses_a_write_and_names_it(tmp_path, capsys):
    module = _module()

    class Refusing(SpyWriter):
        def __init__(self):
            super().__init__(fail_on="shelve_pull", error=GhError)

    code = module.main(["--ledger", str(tmp_path / "l.jsonl"), "--apply"], registry=lambda: _REGISTRY,
                       trees=lambda: (lambda t: ()), writer=Refusing,
                       read_repo=lambda repo: snap(pulls=[pull(1, 30)]),
                       read_issue=lambda repo, n: None, now=lambda: NOW, environ={},
                       state_dir=tmp_path)
    assert code == 1
    assert "GitHub refused to shelve wphelper#1" in capsys.readouterr().err


def test_cli_without_a_ledger_path_is_misconfigured():
    assert _main([]) == 2


def test_cli_takes_the_ledger_from_the_environment(tmp_path):
    ledger = tmp_path / "l.jsonl"
    assert _main([], environ={"SHELVE_LEDGER_PATH": str(ledger)}) == 0
    assert ledger.exists()


def test_cli_apply_without_the_label_exits_two_and_writes_nothing(tmp_path):
    writers: list = []
    ledger = tmp_path / "l.jsonl"
    code = _main(["--ledger", str(ledger), "--apply"],
                 snapshot=snap(pulls=[pull(1, 30)], labels=()), writers=writers)
    assert code == 2
    assert writers[0].calls == []
    assert not ledger.exists()


def test_cli_could_not_look_when_github_fails(tmp_path):
    from oversteward.board.client import GhError

    def broken(_repo):
        raise GhError("gh exited 1")

    module = _module()
    code = module.main(["--ledger", str(tmp_path / "l.jsonl")], registry=lambda: _REGISTRY,
                       trees=lambda: (lambda t: ()), read_repo=broken, now=lambda: NOW, environ={},
                       state_dir=tmp_path)
    assert code == 1
    assert not (tmp_path / "l.jsonl").exists()


def test_cli_refuses_a_ledger_outside_the_state_directory(tmp_path):
    outside = tmp_path / "elsewhere" / "l.jsonl"
    assert _main(["--ledger", str(outside)], state_dir=tmp_path / "state") == 2
    assert not outside.exists()


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def test_cli_reads_real_worktrees_through_the_doctor(tmp_path):
    origin, primary, linked = tmp_path / "origin.git", tmp_path / "primary", tmp_path / "linked"
    _git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", str(origin), str(primary), cwd=tmp_path)
    _git("commit", "--allow-empty", "-m", "base", cwd=primary)
    _git("push", "origin", "HEAD:main", cwd=primary)
    _git("fetch", "origin", cwd=primary)
    _git("worktree", "add", "-b", "session/x", str(linked), cwd=primary)
    _git("commit", "--allow-empty", "-m", "unlanded", cwd=linked)

    target = SweepTarget(WP, frozenset({"main"}), "main", primary)
    (found,) = _module().doctor_trees()(target)

    assert found.path == linked and found.branch == "session/x"
    assert found.landed is False and not found.missing


def test_cli_reads_the_real_registry_targets():
    ids = [t.repo.id for t in targets_from_registry(_module().load_registry())]
    assert {"oversteward", "wphelper", "grantspider", "aigranthelper"} <= set(ids)
