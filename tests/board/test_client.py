# ABOUTME: Tests for the gh transport — which calls it makes, and that a truncated
# ABOUTME: read refuses rather than reporting a smaller estate than exists.

from __future__ import annotations

import pytest

from oversteward.board.client import (
    CLOSED_LIMIT,
    LABEL_LIMIT,
    OPEN_LIMIT,
    TruncatedReadError,
    read_repo,
)
from oversteward.board.config import RepoRef

GS = RepoRef(id="grantspider", full_name="NathanKrupa/grantspider")


def raw(number: int, **overrides) -> dict:
    base = {
        "number": number,
        "title": f"issue {number}",
        "url": f"https://github.com/NathanKrupa/grantspider/issues/{number}",
        "state": "OPEN",
        "labels": [],
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-10T00:00:00Z",
        "closedAt": None,
        "body": "",
    }
    base.update(overrides)
    return base


class Recorder:
    """Answers each gh call from a script and records what was asked."""

    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> list:
        self.calls.append(args)
        key = " ".join(args[:2])
        if "--state" in args:
            key += " " + args[args.index("--state") + 1]
        return self.answers[key]


def test_reads_open_issues_then_closed_issues_carrying_any_epic_label():
    gh = Recorder(
        {
            "issue list open": [raw(1), raw(2, labels=[{"name": "epic:x"}])],
            "label list": [{"name": "bug"}, {"name": "epic:x"}, {"name": "epic:y"}],
            "issue list closed": [
                raw(3, state="CLOSED", closedAt="2026-09-05T00:00:00Z", labels=[{"name": "epic:x"}])
            ],
        }
    )

    issues = read_repo(GS, run=gh)

    assert [i.number for i in issues] == [1, 2, 3]
    assert all(i.repo == "grantspider" for i in issues)
    closed_call = next(c for c in gh.calls if "closed" in c)
    assert "--search" in closed_call
    assert closed_call[closed_call.index("--search") + 1] == 'label:"epic:x","epic:y"'
    assert all(
        "--repo" in c and c[c.index("--repo") + 1] == "NathanKrupa/grantspider" for c in gh.calls
    )


def test_no_epic_labels_means_no_closed_read_at_all():
    gh = Recorder(
        {
            "issue list open": [raw(1)],
            "label list": [{"name": "bug"}],
        }
    )

    issues = read_repo(GS, run=gh)

    assert [i.number for i in issues] == [1]
    assert not any("closed" in c for c in gh.calls)


@pytest.mark.parametrize(
    ("key", "limit"),
    [
        ("issue list open", OPEN_LIMIT),
        ("label list", LABEL_LIMIT),
        ("issue list closed", CLOSED_LIMIT),
    ],
)
def test_a_page_that_fills_its_limit_is_a_truncated_read_not_an_answer(key, limit):
    answers = {
        "issue list open": [raw(1)],
        "label list": [{"name": "epic:x"}],
        "issue list closed": [raw(9, state="CLOSED", labels=[{"name": "epic:x"}])],
    }
    filler = {"name": "epic:z"} if key == "label list" else raw(1)
    answers[key] = [filler] * limit

    with pytest.raises(TruncatedReadError, match="grantspider"):
        read_repo(GS, run=Recorder(answers))


def test_read_estate_keys_by_registry_id_in_the_order_given():
    from oversteward.board.client import read_estate
    from oversteward.board.models import Issue

    ag = RepoRef(id="aigranthelper", full_name="NathanKrupa/aigranthelper")
    fake = lambda repo: (Issue.from_gh(repo.id, raw(1)),)

    estate = read_estate([GS, ag], reader=fake)

    assert list(estate) == ["grantspider", "aigranthelper"]
    assert estate["aigranthelper"][0].repo == "aigranthelper"


def test_read_estate_propagates_a_failed_repository_rather_than_dropping_it():
    from oversteward.board.client import GhError, read_estate

    def fail(repo):
        raise GhError(f"{repo.name}: gh exited 1")

    with pytest.raises(GhError, match="grantspider"):
        read_estate([GS], reader=fail)
