# ABOUTME: Tests for the Estate Brief — the service's choices, the note it renders, and the CLI's exits.
# ABOUTME: GitHub and Railway are fakes passed in as parameters; every note goes to a tmp path.

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oversteward.board.client import GhError, TruncatedReadError
from oversteward.board.config import RepoRef, github_repos_from_registry
from oversteward.brief.client import MERGED_LIMIT, read_activity
from oversteward.brief.compose import (
    SHELVED_PLACEHOLDER,
    SHIPPED_PER_REPO,
    compose,
    liveness_urgent,
    render,
)
from oversteward.liveness.client import RailwayUnavailableError
from oversteward.liveness.models import LivenessReport, ServiceState

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


def _brief(gh: FakeGh, repos=(AG, GS), read_urgent=_quiet):
    return compose(list(repos), now=NOW, window=WINDOW, read_urgent=read_urgent, read=_reader(gh))


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
    assert brief.urgent_blind is False


def test_a_down_service_is_rendered_above_everything_else():
    text = render(_brief(FakeGh(), read_urgent=lambda: ("Railway: aigranthelper / web is CRASHED",)))

    assert "- Railway: aigranthelper / web is CRASHED" in text
    assert text.index("## URGENT") < text.index("## Shipped")


def test_a_liveness_sweep_that_could_not_look_is_named_not_hidden():
    def blind():
        raise RailwayUnavailableError("railway exited 1 reading services")

    brief = _brief(FakeGh(), read_urgent=blind)

    assert brief.urgent_blind is True
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


def test_the_note_carries_a_date_line_and_the_shelved_placeholder():
    text = render(_brief(FakeGh()))

    assert "Date: 2026-10-21 (Wednesday)" in text
    assert text.rstrip().endswith(SHELVED_PLACEHOLDER)


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


def _main(argv, *, registry=_REGISTRY, gh=None, urgent=_quiet, environ=None):
    gh = gh or FakeGh()
    return _module().main(
        argv,
        registry=lambda: registry,
        urgent=lambda _loaded: urgent,
        now=lambda: NOW,
        read=_reader(gh),
        environ=environ or {},
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

    assert _main([], environ={"ESTATE_BRIEF_PATH": str(out)}) == 0
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
