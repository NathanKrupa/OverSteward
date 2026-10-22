# ABOUTME: Tests for the Estate Brief — the service's choices, the note it renders, and the CLI's exits.
# ABOUTME: GitHub and Railway are fakes passed in as parameters; every note goes to a tmp path.

from __future__ import annotations

import importlib.util
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oversteward.board.client import GhError, TruncatedReadError
from oversteward.board.config import RepoRef, github_repos_from_registry
from oversteward.brief.client import (
    ASK_LIMIT,
    MERGED_LIMIT,
    AskThread,
    issue_is_open,
    read_activity,
    read_thread,
)
from oversteward.brief.compose import (
    QUESTION_CHARS,
    SHIPPED_PER_REPO,
    KnownIssue,
    ShelvedRead,
    UrgentRead,
    compose,
    known_failures,
    liveness_urgent,
    question_text,
    render,
)
from oversteward.board.client import NotFoundError
from oversteward.liveness.client import RailwayConfigError, RailwayUnavailableError
from oversteward.liveness.models import LivenessReport, ServiceState
from oversteward.shelve.ledger import LedgerEntry, to_lines
from oversteward.shelve.sweep import run_entry

REPO_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 10, 21, 5, 30, tzinfo=UTC)
WINDOW = timedelta(hours=24)
SINCE = NOW - WINDOW

AG = RepoRef("aigranthelper", "NathanKrupa/aigranthelper")
GS = RepoRef("grantspider", "NathanKrupa/grantspider")
OS = RepoRef("oversteward", "NathanKrupa/OverSteward")


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _pr(repo: RepoRef, number: int, title: str, merged_at: datetime | None, state="MERGED"):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo.full_name}/pull/{number}",
        "state": state,
        "mergedAt": _iso(merged_at) if merged_at else None,
    }


def _ask(repo: RepoRef, number: int, title: str, created: datetime):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo.full_name}/issues/{number}",
        "state": "OPEN",
        "labels": [{"name": "needs-input"}],
        "createdAt": _iso(created),
        "updatedAt": _iso(NOW - timedelta(hours=1)),
    }


class FakeGh:
    """Answers ``gh`` argv by (repository, verb); records every call."""

    def __init__(self, pulls=None, asks=None):
        self.pulls = pulls or {}
        self.asks = asks or {}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]):
        self.calls.append(args)
        repo = args[args.index("--repo") + 1]
        return list((self.pulls if args[0] == "pr" else self.asks).get(repo, []))


def _reader(gh: FakeGh):
    return lambda repo, since: read_activity(repo, since, run=gh)


def _quiet():
    return ()


def _no_thread(repo, number):
    return AskThread(body="", comments=())


def _ran():
    return (run_entry("dry", NOW - timedelta(hours=1), 0),)


def _brief(gh: FakeGh, repos=(AG, GS), read_urgent=_quiet, thread=_no_thread, shelved=_ran):
    return compose(list(repos), now=NOW, window=WINDOW, read_urgent=read_urgent, read=_reader(gh),
                   read_thread=thread, read_shelved=shelved)


# --- shipped ---------------------------------------------------------------


def test_an_empty_window_renders_zero_shipped():
    text = render(_brief(FakeGh()))

    assert "0 shipped in the last 24 hours." in text
    assert "**" not in text


def test_three_merges_across_two_repos_render_both_groups():
    gh = FakeGh(
        pulls={
            AG.full_name: [
                _pr(AG, 11, "Pantry search filter", NOW - timedelta(hours=3)),
                _pr(AG, 12, "Grant calendar export", NOW - timedelta(hours=2)),
            ],
            GS.full_name: [_pr(GS, 21, "Faster 990 parse", NOW - timedelta(hours=5))],
        }
    )

    brief = _brief(gh)
    text = render(brief)

    assert brief.shipped_count == 3
    assert "3 shipped across 2 repos in the last 24 hours." in text
    assert "**aigranthelper** (2)" in text
    assert "**grantspider** (1)" in text
    for line in ("- Pantry search filter (#11)", "- Grant calendar export (#12)",
                 "- Faster 990 parse (#21)"):
        assert line in text


def test_a_pull_request_closed_without_merging_is_not_shipped():
    gh = FakeGh(
        pulls={
            AG.full_name: [
                _pr(AG, 11, "Merged one", NOW - timedelta(hours=3)),
                _pr(AG, 13, "Closed unmerged", None, state="CLOSED"),
            ],
        }
    )

    brief = _brief(gh)
    text = render(brief)

    assert brief.shipped_count == 1
    assert "Closed unmerged" not in text
    assert "**aigranthelper** (1)" in text


def test_the_window_opens_at_exactly_now_minus_the_window():
    gh = FakeGh(
        pulls={
            AG.full_name: [
                _pr(AG, 1, "At the edge", SINCE),
                _pr(AG, 2, "One second early", SINCE - timedelta(seconds=1)),
            ],
        }
    )

    text = render(_brief(gh))

    assert "At the edge (#1)" in text
    assert "One second early" not in text


def test_a_long_repo_list_is_capped_with_a_count_of_the_rest():
    pulls = [_pr(AG, n, f"Change {n}", NOW - timedelta(minutes=n)) for n in range(1, 6)]
    text = render(_brief(FakeGh(pulls={AG.full_name: pulls})))

    listed = [line for line in text.splitlines() if line.startswith("- Change")]
    assert len(listed) == SHIPPED_PER_REPO
    assert f"- +{5 - SHIPPED_PER_REPO} more" in text
    assert "**aigranthelper** (5)" in text


def test_the_merged_search_reaches_back_a_day_before_the_window_opens():
    gh = FakeGh()
    read_activity(AG, SINCE, run=gh)

    (pr_call,) = [c for c in gh.calls if c[0] == "pr"]
    assert pr_call[pr_call.index("--state") + 1] == "merged"
    assert pr_call[pr_call.index("--search") + 1] == "merged:>=2026-10-19"


def test_the_ask_query_is_open_issues_labelled_needs_input():
    gh = FakeGh()
    read_activity(AG, SINCE, run=gh)

    (issue_call,) = [c for c in gh.calls if c[0] == "issue"]
    assert issue_call[issue_call.index("--state") + 1] == "open"
    assert issue_call[issue_call.index("--label") + 1] == "needs-input"


def test_a_full_page_of_asks_is_refused():
    rows = [_ask(AG, n, "x", NOW) for n in range(ASK_LIMIT)]

    with pytest.raises(TruncatedReadError):
        read_activity(AG, SINCE, run=FakeGh(asks={AG.full_name: rows}))


def test_a_full_page_is_refused_rather_than_read_as_the_estate():
    rows = [_pr(AG, n, "x", NOW) for n in range(MERGED_LIMIT)]

    with pytest.raises(TruncatedReadError):
        read_activity(AG, SINCE, run=FakeGh(pulls={AG.full_name: rows}))


# --- the one ask -----------------------------------------------------------


def test_two_pending_asks_render_only_the_oldest():
    gh = FakeGh(
        asks={
            AG.full_name: [_ask(AG, 40, "Newer question", NOW - timedelta(days=2))],
            GS.full_name: [_ask(GS, 30, "Older question", NOW - timedelta(days=9))],
        }
    )

    text = render(_brief(gh))

    assert "[Older question](https://github.com/NathanKrupa/grantspider/issues/30)" in text
    assert "Newer question" not in text


def test_no_pending_ask_says_nothing_is_waiting():
    assert "Nothing is waiting on you." in render(_brief(FakeGh()))


# --- URGENT ----------------------------------------------------------------


def test_urgent_is_absent_when_nothing_is_down():
    brief = _brief(FakeGh())

    assert "URGENT" not in render(brief)
    assert brief.urgent_read is UrgentRead.MEASURED


def test_a_down_service_is_rendered_above_everything_else():
    text = render(_brief(FakeGh(), read_urgent=lambda: ("Railway: aigranthelper / web is CRASHED",)))

    assert "- Railway: aigranthelper / web is CRASHED" in text
    assert text.index("## URGENT") < text.index("## Shipped")


def test_a_liveness_sweep_that_could_not_look_is_named_not_hidden():
    def blind():
        raise RailwayUnavailableError("railway exited 1 reading services")

    brief = _brief(FakeGh(), read_urgent=blind)

    assert brief.urgent_read is UrgentRead.BLIND
    assert "Could not check Railway — railway exited 1" in render(brief)


def test_liveness_urgent_names_only_services_that_are_down_or_unclassified():
    states = (
        ServiceState("aigranthelper", "web", "CRASHED", stopped=False),
        ServiceState("aigranthelper", "worker", "SUCCESS", stopped=False),
        ServiceState("grantspider", "cron", "SUCCESS", stopped=True),
        ServiceState("grantspider", "odd", "MYSTERY", stopped=False),
    )

    lines = liveness_urgent([], sweeper=lambda _p: LivenessReport(states=states))

    assert lines == (
        "Railway: aigranthelper / web is CRASHED",
        "Railway: grantspider / odd is MYSTERY",
    )


# --- note shape ------------------------------------------------------------


def test_the_note_carries_a_date_line_and_ends_with_the_shelved_section():
    text = render(_brief(FakeGh()))

    assert "Date: 2026-10-21 (Wednesday)" in text
    assert text.rstrip().endswith("## Shelved overnight\n\nNothing shelved or reopened.")


# --- registry --------------------------------------------------------------


def test_every_context_with_a_github_remote_is_read_dispatch_target_or_not():
    registry = {
        "contexts": [
            {"id": "oversteward", "repo": "https://github.com/NathanKrupa/OverSteward.git",
             "dispatch_target": True},
            {"id": "billions", "repo": "https://github.com/NathanKrupa/billions.git"},
            {"id": "local", "repo": "/home/natha/somewhere"},
        ]
    }

    assert github_repos_from_registry(registry) == [
        RepoRef("oversteward", "NathanKrupa/OverSteward"),
        RepoRef("billions", "NathanKrupa/billions"),
    ]


# --- CLI -------------------------------------------------------------------


def _module():
    spec = importlib.util.spec_from_file_location(
        "estate_brief", REPO_ROOT / "scripts" / "estate_brief.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REGISTRY = {
    "contexts": [{"id": "aigranthelper", "repo": "https://github.com/NathanKrupa/aigranthelper"}]
}


_LEDGER: dict[str, Path] = {}


@pytest.fixture(autouse=True)
def _sweep_ledger(tmp_path):
    """A ledger holding one completed dry run, inside a state directory, for every CLI test."""
    state = tmp_path / "state"
    state.mkdir()
    path = state / "shelve-ledger.jsonl"
    path.write_text(to_lines(_ran()), encoding="utf-8")
    _LEDGER.update(state=state, path=path)


def _main(argv, *, registry=_REGISTRY, gh=None, urgent=_quiet, environ=None, known=None):
    gh = gh or FakeGh()
    env = {"SHELVE_LEDGER_PATH": str(_LEDGER["path"])} if environ is None else environ
    return _module().main(
        argv,
        registry=lambda: registry,
        known=lambda: known or {},
        urgent=lambda _loaded, _known, _repos: urgent,
        now=lambda: NOW,
        read=_reader(gh),
        thread=_no_thread,
        environ=env,
        state_dir=_LEDGER["state"],
    )


def test_the_real_registry_reads_beyond_the_dispatch_targets():
    ids = [r.id for r in github_repos_from_registry(_module().load_registry())]
    assert {"oversteward", "aigranthelper", "grantspider", "billions"} <= set(ids)


def test_cli_measured_answer_writes_the_note_and_exits_zero(tmp_path):
    out = tmp_path / "Estate Brief.md"

    assert _main(["--out", str(out)]) == 0
    assert "0 shipped in the last 24 hours." in out.read_text(encoding="utf-8")


def test_cli_takes_the_note_path_from_the_environment(tmp_path):
    out = tmp_path / "Estate Brief.md"

    environ = {"ESTATE_BRIEF_PATH": str(out), "SHELVE_LEDGER_PATH": str(_LEDGER["path"])}
    assert _main([], environ=environ) == 0
    assert out.exists()


def test_cli_with_no_note_path_is_misconfigured():
    assert _main([]) == 2


def test_cli_with_no_github_context_is_misconfigured(tmp_path):
    out = tmp_path / "Estate Brief.md"

    assert _main(["--out", str(out)], registry={"contexts": []}) == 2
    assert not out.exists()


def test_cli_could_not_look_when_github_fails_and_writes_nothing(tmp_path):
    out = tmp_path / "Estate Brief.md"

    def broken(_args):
        raise GhError("gh exited 1")

    assert _main(["--out", str(out)], gh=broken) == 1
    assert not out.exists()


def test_cli_could_not_look_when_the_vault_folder_is_missing(tmp_path):
    out = tmp_path / "unmounted" / "GTD" / "Estate Brief.md"

    assert _main(["--out", str(out)]) == 1
    assert not (tmp_path / "unmounted").exists()


def test_cli_writes_the_note_but_exits_one_when_liveness_is_blind(tmp_path):
    out = tmp_path / "Estate Brief.md"

    def blind():
        raise RailwayUnavailableError("railway CLI not found on PATH")

    assert _main(["--out", str(out)], urgent=blind) == 1
    assert "Could not check Railway" in out.read_text(encoding="utf-8")



def test_cli_writes_the_note_but_exits_two_when_railway_is_not_configured(tmp_path):
    out = tmp_path / "Estate Brief.md"

    def unconfigured():
        raise RailwayConfigError("no Railway projects configured")

    assert _main(["--out", str(out)], urgent=unconfigured) == 2
    text = out.read_text(encoding="utf-8")
    assert "Railway liveness is not configured" in text
    assert "Could not check Railway" not in text

# --- nightly host ----------------------------------------------------------

OPS = REPO_ROOT / "ops" / "wsl"


def _directives(path: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            found.setdefault(key, []).append(value)
    return found


def test_the_timer_runs_nightly_after_the_checkout_sync_and_catches_up():
    timer = _directives(OPS / "estate-brief.timer")

    assert timer["OnCalendar"] == ["*-*-* 05:30:00"]
    assert timer["Persistent"] == ["true"]


def test_the_service_writes_the_vault_note_with_railway_on_path():
    service = _directives(OPS / "estate-brief.service")
    (exec_start,) = service["ExecStart"]
    argv = shlex.split(exec_start)

    assert service["Type"] == ["oneshot"]
    assert argv[:2] == [
        "/home/natha/OverSteward/.venv/bin/python",
        "/home/natha/OverSteward/scripts/estate_brief.py",
    ]
    assert argv[2:] == [
        "--out",
        "/mnt/c/Users/natha/OneDrive/Documents/Nathan Writing/Obsidian/GTD/Estate Brief.md",
    ]
    path_line = next(v for v in service["Environment"] if v.startswith("PATH="))
    assert "/home/natha/.railway/bin" in path_line.split("=", 1)[1].split(":")


@pytest.mark.parametrize("name", ["estate-brief.service", "estate-brief.timer"])
def test_the_units_open_with_aboutme(name):
    first = (OPS / name).read_text(encoding="utf-8").splitlines()[:2]
    assert all(line.startswith("# ABOUTME: ") for line in first)


# --- shelved overnight -----------------------------------------------------


def _line(action, number, *, mode="dry", rule="pr-idle", idle=30, hours_ago=1, kind="pr",
          repo="wphelper", reason="no commit, comment or review"):
    return LedgerEntry(
        at=NOW - timedelta(hours=hours_ago), mode=mode, repo=repo, kind=kind, number=number,
        ref=None, title=f"Item {number}", url=f"https://github.com/x/{number}", rule=rule,
        action=action, idle_days=idle, reason=reason,
    )


def _shelved_text(*entries, ran=True):
    rows = (*entries, *(_ran() if ran else ()))
    return render(_brief(FakeGh(), shelved=lambda: rows))


def test_dry_lines_render_as_would_never_as_done():
    text = _shelved_text(_line("shelve", 1), _line("close", 2, rule="finding-idle", kind="issue"))

    assert "Dry run — nothing below was changed on GitHub." in text
    assert "- would shelve wphelper #1 — Item 1, idle 30d" in text
    assert "- would close wphelper #2" in text
    assert "- shelved " not in text and "- closed " not in text


def test_applied_lines_render_as_done_without_the_dry_run_caveat():
    text = _shelved_text(_line("shelve", 1, mode="applied"), _line("reopen", 3, mode="applied"))

    assert "- shelved wphelper #1" in text
    assert "- reopened wphelper #3" in text
    assert "Dry run" not in text


def test_a_failed_write_is_named_in_the_brief():
    text = _shelved_text(_line("failed", 3, mode="applied", reason="reopen: HTTP 422"))
    assert "- gh failed (reopen: HTTP 422) on wphelper #3 — Item 3" in text


def test_report_and_candidate_lines_are_counted_not_listed():
    text = _shelved_text(
        _line("report", None, rule="branch-no-pr", kind="branch"),
        _line("report", None, rule="branch-no-pr", kind="branch", repo="grantspider"),
        _line("report", None, rule="worktree-unlanded", kind="worktree"),
        _line("candidate", 9, rule="incubator-candidate", kind="issue", idle=120),
    )
    assert "Nothing shelved or reopened." in text
    assert "Reported, untouched: 2 branches with no pull request, 1 unlanded worktree." in text
    assert "1 issue idle 90+ days: Incubator candidates." in text


def test_lines_outside_the_window_are_not_read():
    brief = _brief(FakeGh(), shelved=lambda: (_line("shelve", 1, hours_ago=25), *_ran()))
    assert brief.shelved.entries == ()
    assert "would shelve" not in render(brief)


def test_a_repeated_dry_run_lists_each_item_once():
    text = _shelved_text(_line("shelve", 1, hours_ago=5), _line("shelve", 1, hours_ago=1))
    assert text.count("would shelve wphelper #1") == 1


def test_no_completed_run_in_the_window_says_so_rather_than_nothing_shelved():
    brief = _brief(FakeGh(), shelved=lambda: (run_entry("dry", NOW - timedelta(hours=30), 0),))
    text = render(brief)

    assert brief.shelved.read is ShelvedRead.NO_RUN
    assert "did not finish a run in the last 24 hours" in text
    assert "Nothing shelved" not in text


def test_a_missing_ledger_is_no_run_and_an_unreadable_one_is_named():
    def missing():
        raise FileNotFoundError(2, "No such file", "/state/l.jsonl")

    def torn():
        raise ValueError("ledger line 3 does not parse")

    assert _brief(FakeGh(), shelved=missing).shelved.read is ShelvedRead.NO_RUN
    unreadable = _brief(FakeGh(), shelved=torn)
    assert unreadable.shelved.read is ShelvedRead.UNREADABLE
    assert "Could not read the sweep ledger — ledger line 3" in render(unreadable)


def test_no_ledger_configured_says_so():
    brief = compose([AG], now=NOW, window=WINDOW, read_urgent=_quiet, read=_reader(FakeGh()),
                    read_thread=_no_thread)
    assert brief.shelved.read is ShelvedRead.UNCONFIGURED
    assert "No sweep ledger configured." in render(brief)


# --- the one ask: its question, and the Incubator fallback ------------------


def test_the_ask_renders_its_latest_question_trimmed_under_the_link():
    thread = AskThread(body="Body text.", comments=(
        "@nathankrupa question: an older question?",
        "Some chatter.",
        "**@NathanKrupa question:** approve the   over-cap PR?\n\n**Plan considered:** one PR.",
        "[answering @nathankrupa question]: yes, approved",
    ))
    gh = FakeGh(asks={AG.full_name: [_ask(AG, 40, "Approve it?", NOW - timedelta(days=2))]})
    text = render(_brief(gh, thread=lambda repo, n: thread))

    link = "[Approve it?](https://github.com/NathanKrupa/aigranthelper/issues/40) — aigranthelper #40"
    assert f"{link}\n\n> approve the over-cap PR? **Plan considered:** one PR." in text
    assert "older question" not in text and "yes, approved" not in text


def test_the_ask_falls_back_to_the_issue_body():
    assert question_text(AskThread(body="  Which option,\nA or B?  ", comments=("hi",))) == (
        "Which option, A or B?"
    )


def test_a_long_question_is_trimmed():
    text = question_text(AskThread(body="", comments=("@nathankrupa question: " + "x" * 2000,)))
    assert len(text) == QUESTION_CHARS and text.endswith("…")


def test_the_question_is_read_from_the_asks_own_repository():
    asked = []
    gh = FakeGh(asks={GS.full_name: [_ask(GS, 30, "Q", NOW - timedelta(days=9))]})
    _brief(gh, thread=lambda repo, n: asked.append((repo, n)) or AskThread("b", ()))
    assert asked == [(GS, 30)]


def test_with_no_ask_the_longest_idle_incubator_candidate_is_offered():
    text = _shelved_text(
        _line("candidate", 7, rule="incubator-candidate", kind="issue", idle=95),
        _line("candidate", 8, rule="incubator-candidate", kind="issue", idle=200),
    )
    assert "Move to the Incubator? [Item 8](https://github.com/x/8) — wphelper #8, idle 200 days." in text


def test_an_ask_outranks_an_incubator_candidate():
    gh = FakeGh(asks={AG.full_name: [_ask(AG, 40, "Real ask", NOW - timedelta(days=2))]})
    rows = (_line("candidate", 8, rule="incubator-candidate", kind="issue", idle=200), *_ran())
    text = render(_brief(gh, shelved=lambda: rows))
    assert "Move to the Incubator?" not in text and "Real ask" in text


def test_read_thread_asks_for_the_newest_comments():
    calls = []

    def gh(args):
        calls.append(args)
        return {"data": {"repository": {"issue": {"body": "B", "comments": {"nodes": [{"body": "c"}]}}}}}

    assert read_thread(AG, 40, run=gh) == AskThread("B", ("c",))
    assert "comments(last: 100)" in calls[0][3]
    assert calls[0][-2:] == ["-F", "number=40"]


# --- KNOWN failures --------------------------------------------------------


_DOWN = (ServiceState("aigranthelper", "monitor_indexation", "CRASHED", stopped=True),
         ServiceState("aigranthelper", "web", "CRASHED", stopped=False))


def _urgent(known, open_issues=frozenset({("aigranthelper", 2481)})):
    return liveness_urgent([], sweeper=lambda _p: LivenessReport(states=_DOWN), known=known,
                           is_open=lambda issue: (issue.repo, issue.number) in open_issues)


def test_a_recorded_open_issue_marks_the_service_known():
    lines = _urgent({"aigranthelper/monitor_indexation": KnownIssue("aigranthelper", 2481)})
    assert lines == (
        "KNOWN→aigranthelper#2481 — Railway: aigranthelper / monitor_indexation is CRASHED",
        "Railway: aigranthelper / web is CRASHED",
    )


@pytest.mark.parametrize("key", ["monitor_indexation", "aigranthelper/monitor",
                                 "aigranthelper/Monitor_Indexation", "aigranthelper/monitor_indexation "])
def test_known_requires_the_exact_recorded_key(key):
    lines = _urgent({key: KnownIssue("aigranthelper", 2481)})
    assert not any(line.startswith("KNOWN") for line in lines)


def test_a_recorded_issue_that_closed_is_a_fresh_alarm_again():
    lines = _urgent({"aigranthelper/monitor_indexation": KnownIssue("aigranthelper", 2481)},
                    open_issues=frozenset())
    assert lines[0] == ("Railway: aigranthelper / monitor_indexation is CRASHED "
                        "(recorded issue aigranthelper#2481 is no longer open)")


def test_known_failures_validates_every_entry():
    assert known_failures({"railway": {"aigranthelper/x": "aigranthelper#1"}}, [AG]) == {
        "aigranthelper/x": KnownIssue("aigranthelper", 1)}
    for bad in ({"x": "aigranthelper#1"}, {"aigranthelper/x": "aigranthelper 1"},
                {"aigranthelper/x": "nosuchrepo#1"}, {"aigranthelper/x": "#1"}):
        with pytest.raises(ValueError):
            known_failures({"railway": bad}, [AG])


def test_the_recorded_mapping_file_is_valid_and_seeds_monitor_indexation():
    module = _module()
    known = known_failures(module.load_known(), github_repos_from_registry(module.load_registry()))
    assert known["aigranthelper/monitor_indexation"] == KnownIssue("aigranthelper", 2481)


def test_issue_is_open_is_false_for_a_pull_request_a_closed_issue_or_a_missing_one():
    answers = {"repos/NathanKrupa/aigranthelper/issues/1": {"state": "open"},
               "repos/NathanKrupa/aigranthelper/issues/2": {"state": "closed"},
               "repos/NathanKrupa/aigranthelper/issues/3": {"state": "open", "pull_request": {}}}

    def gh(args):
        if args[1] not in answers:
            raise NotFoundError("HTTP 404")
        return answers[args[1]]

    assert [issue_is_open(AG, n, run=gh) for n in (1, 2, 3, 4)] == [True, False, False, False]


# --- CLI: the ledger and the mapping ----------------------------------------


def test_cli_without_a_sweep_ledger_writes_the_note_and_exits_two(tmp_path):
    out = tmp_path / "Estate Brief.md"
    assert _main(["--out", str(out)], environ={}) == 2
    assert "No sweep ledger configured." in out.read_text(encoding="utf-8")


def test_cli_with_no_run_in_the_window_writes_the_note_and_exits_one(tmp_path):
    _LEDGER["path"].write_text("", encoding="utf-8")
    out = tmp_path / "Estate Brief.md"
    assert _main(["--out", str(out)]) == 1
    assert "did not finish a run" in out.read_text(encoding="utf-8")


def test_cli_could_not_look_outranks_not_configured(tmp_path):
    _LEDGER["path"].write_text("", encoding="utf-8")

    def unconfigured():
        raise RailwayConfigError("no Railway projects configured")

    assert _main(["--out", str(tmp_path / "b.md")], urgent=unconfigured) == 1


def test_cli_refuses_a_ledger_outside_the_state_directory(tmp_path):
    out = tmp_path / "Estate Brief.md"
    environ = {"SHELVE_LEDGER_PATH": str(tmp_path / "elsewhere.jsonl")}
    assert _main(["--out", str(out)], environ=environ) == 2
    assert not out.exists()


def test_cli_refuses_a_malformed_known_failure_map(tmp_path):
    out = tmp_path / "Estate Brief.md"
    assert _main(["--out", str(out)], known={"railway": {"monitor": "aigranthelper#1"}}) == 2
    assert not out.exists()


def test_cli_reads_the_ledger_it_is_given(tmp_path):
    rows = (_line("shelve", 7), *_ran())
    _LEDGER["path"].write_text(to_lines(rows), encoding="utf-8")
    out = tmp_path / "Estate Brief.md"
    assert _main(["--out", str(out)]) == 0
    assert "- would shelve wphelper #7" in out.read_text(encoding="utf-8")


# --- nightly host: the sweep runs first, in dry-run ------------------------


def test_the_service_runs_the_sweep_first_in_dry_run_and_shares_the_ledger():
    service = _directives(OPS / "estate-brief.service")
    (pre,) = service["ExecStartPre"]

    assert pre.startswith("-"), "a failed sweep must not stop the brief"
    assert shlex.split(pre[1:]) == [
        "/home/natha/OverSteward/.venv/bin/python",
        "/home/natha/OverSteward/scripts/shelve_sweep.py",
    ], "the sweep stays dry-run until Nathan approves --apply"
    ledger_env = [v for v in service["Environment"] if v.startswith("SHELVE_LEDGER_PATH=")]
    assert ledger_env == ["SHELVE_LEDGER_PATH=/home/natha/.local/state/oversteward/shelve-ledger.jsonl"]
