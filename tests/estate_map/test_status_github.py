# ABOUTME: Tests for the gh connector behind estate-map status — every failure to read is CouldNotLook.
# ABOUTME: A failed gh call, a full page or an unknown repo must never come back as an empty list.

from __future__ import annotations

import subprocess

import pytest

from oversteward.estate_map.checkouts import CouldNotLook
from oversteward.estate_map.status import Item
from oversteward.estate_map.status_github import fetcher, full_name, open_items
from oversteward.intake.github import GhError

REGISTRY = {
    "contexts": [
        {"id": "grantspider", "repo": "https://github.com/NathanKrupa/grantspider.git"},
        {"id": "nourl"},
    ]
}


def test_full_name_comes_from_the_registry_repo_url():
    assert full_name(REGISTRY, "grantspider") == "NathanKrupa/grantspider"


@pytest.mark.parametrize("repo", ["nourl", "absent"])
def test_full_name_without_a_github_url_could_not_look(repo):
    with pytest.raises(CouldNotLook, match=repo):
        full_name(REGISTRY, repo)


def _rows(issues, prs):
    def run(args):
        return issues if args[0] == "issue" else prs

    return run


def test_open_items_reads_issues_and_prs_with_their_files():
    run = _rows(
        [{"number": 1, "title": "a", "body": "b", "labels": []}],
        [{"number": 2, "title": "c", "body": None, "files": [{"path": "x.py"}]}],
    )
    assert open_items("grantspider", "NathanKrupa/grantspider", run=run) == [
        Item("grantspider", "issue", 1, "a", "b"),
        Item("grantspider", "pr", 2, "c", "", ("x.py",)),
    ]


def test_a_gh_failure_is_could_not_look():
    def run(args):
        raise GhError("gh issue list failed (exit 1): HTTP 502")

    with pytest.raises(CouldNotLook, match="grantspider: .*HTTP 502"):
        open_items("grantspider", "NathanKrupa/grantspider", run=run)


def test_a_full_page_is_could_not_look():
    run = _rows([{"number": n} for n in range(1000)], [])
    with pytest.raises(CouldNotLook, match="filled the page"):
        open_items("grantspider", "NathanKrupa/grantspider", run=run)


def test_a_full_pr_page_is_could_not_look():
    run = _rows([], [{"number": n} for n in range(200)])
    with pytest.raises(CouldNotLook, match="filled the page"):
        open_items("grantspider", "NathanKrupa/grantspider", run=run)


def test_the_real_gh_wrapper_turns_a_non_zero_exit_into_could_not_look():
    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="could not resolve host")

    fetch = fetcher(REGISTRY, run_process=failing)
    with pytest.raises(CouldNotLook, match="could not resolve host"):
        fetch("grantspider")


def test_unparseable_gh_output_is_could_not_look():
    def garbled(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="<html>", stderr="")

    with pytest.raises(CouldNotLook, match="grantspider"):
        fetcher(REGISTRY, run_process=garbled)("grantspider")
