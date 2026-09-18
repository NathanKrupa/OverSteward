# ABOUTME: Tests for how an issue's body names its children — #N and same-repo issue URLs,
# ABOUTME: never another repository's issues and never pull requests.

from __future__ import annotations

from oversteward.board.models import Issue

RAW = {
    "number": 1,
    "title": "Epic: x",
    "state": "OPEN",
    "url": "https://github.com/NathanKrupa/aigranthelper/issues/1",
    "labels": [],
    "createdAt": "2026-09-01T00:00:00Z",
    "updatedAt": "2026-09-10T00:00:00Z",
    "closedAt": None,
}


def with_body(body: str) -> Issue:
    return Issue.from_gh("aigranthelper", {**RAW, "body": body})


def test_hash_refs_and_same_repo_issue_urls_are_children():
    issue = with_body(
        "- [x] #5\n"
        "- [ ] https://github.com/NathanKrupa/aigranthelper/issues/7\n"
        "- [ ] https://github.com/NathanKrupa/aigranthelper/issues/9#issuecomment-1\n"
    )

    assert issue.body_refs == frozenset({5, 7, 9})


def test_another_repositorys_issue_url_is_not_a_child():
    issue = with_body("see https://github.com/NathanKrupa/grantspider/issues/7")

    assert issue.body_refs == frozenset()


def test_a_pull_request_url_is_not_a_child():
    issue = with_body("merged in https://github.com/NathanKrupa/aigranthelper/pull/7")

    assert issue.body_refs == frozenset()


def test_a_ref_inside_a_url_path_is_not_a_hash_ref():
    issue = with_body("https://example.com/#12 and owner/repo#13")

    assert issue.body_refs == frozenset()
