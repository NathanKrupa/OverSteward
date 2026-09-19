# ABOUTME: Tests for the gh transport — which calls it makes, and that a truncated
# ABOUTME: read refuses rather than reporting a smaller estate than exists.

from __future__ import annotations

import subprocess

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


def epic_raw(number: int, body: str, **overrides) -> dict:
    return raw(number, title=f"Epic: {number}", body=body, **overrides)


def rest(number: int, *, state: str = "closed", pull: bool = False) -> dict:
    payload = {
        "number": number,
        "title": f"issue {number}",
        "state": state,
        "body": "",
        "html_url": f"https://github.com/NathanKrupa/grantspider/issues/{number}",
        "labels": [{"name": "bug"}],
        "created_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "closed_at": "2026-07-20T00:00:00Z" if state == "closed" else None,
    }
    if pull:
        payload["pull_request"] = {"url": "…"}
    return payload


class RestRecorder(Recorder):
    """Recorder that also answers per-number REST reads from a ``by_number`` map."""

    def __init__(self, answers: dict[str, list], by_number: dict[int, dict | Exception]):
        super().__init__(answers)
        self.by_number = by_number

    def __call__(self, args: list[str]):
        if args[0] == "api":
            self.calls.append(args)
            number = int(args[1].rsplit("/", 1)[1])
            answer = self.by_number[number]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return super().__call__(args)


def test_body_refs_of_open_epics_that_were_not_fetched_are_read_by_number():
    from oversteward.board.client import NotFoundError

    gh = RestRecorder(
        {
            "issue list open": [
                epic_raw(1, body="- [x] #50\n- [x] #51\n- [ ] #2\n- [x] #52\n- [x] #53"),
                raw(2),
                epic_raw(3, body="#60", state="CLOSED", closedAt="2026-08-01T00:00:00Z"),
                raw(4, body="#61"),
            ],
            "label list": [],
        },
        by_number={
            50: rest(50),  # a closed, label-less child: the missing case
            51: rest(51, pull=True),  # a merged PR: not a child
            52: NotFoundError("HTTP 404"),  # a typo in the body: not a child
            53: rest(53, state="open"),  # open but paged out: still a child
        },
    )

    issues = read_repo(GS, run=gh)

    fetched = {i.number: i for i in issues}
    assert set(fetched) == {1, 2, 3, 4, 50, 53}
    assert fetched[50].state == "CLOSED" and fetched[50].closed_at is not None
    assert fetched[50].labels == frozenset({"bug"})
    assert fetched[50].url.endswith("/issues/50")
    assert fetched[53].state == "OPEN"
    asked = sorted(int(c[1].rsplit("/", 1)[1]) for c in gh.calls if c[0] == "api")
    assert asked == [
        50,
        51,
        52,
        53,
    ]  # not #2 (fetched), not #60 (closed epic), not #61 (not an epic)
    assert all(
        c[1].startswith("repos/NathanKrupa/grantspider/issues/") for c in gh.calls if c[0] == "api"
    )


def test_a_failed_by_number_read_that_is_not_a_404_propagates():
    from oversteward.board.client import GhError

    gh = RestRecorder(
        {"issue list open": [epic_raw(1, body="#50")], "label list": []},
        by_number={50: GhError("gh api failed (exit 1): HTTP 502")},
    )

    with pytest.raises(GhError, match="502"):
        read_repo(GS, run=gh)


def _completed(returncode: int, stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout="", stderr=stderr)


def test_gh_json_turns_a_404_into_not_found(monkeypatch):
    from oversteward.board import client
    from oversteward.board.client import NotFoundError, gh_json

    monkeypatch.setattr(
        client.subprocess, "run", lambda *_a, **_k: _completed(1, "gh: Not Found (HTTP 404)")
    )

    with pytest.raises(NotFoundError, match="HTTP 404"):
        gh_json(["api", "repos/NathanKrupa/grantspider/issues/999999999"])


def test_gh_json_raises_a_plain_gh_error_for_any_other_failure(monkeypatch):
    from oversteward.board import client
    from oversteward.board.client import GhError, NotFoundError, gh_json

    monkeypatch.setattr(
        client.subprocess, "run", lambda *_a, **_k: _completed(4, "gh: set GH_TOKEN")
    )

    with pytest.raises(GhError, match="GH_TOKEN") as caught:
        gh_json(["api", "repos/NathanKrupa/grantspider/issues/1"])
    assert not isinstance(caught.value, NotFoundError)
