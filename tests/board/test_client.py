# ABOUTME: Tests for the gh transport — which calls it makes, and that a truncated
# ABOUTME: read refuses rather than reporting a smaller estate than exists.

from __future__ import annotations

import subprocess

import pytest

from oversteward.board import client
from oversteward.board.client import (
    GhError,
    TruncatedReadError,
    read_repo,
)
from oversteward.board.config import RepoRef

GS = RepoRef(id="grantspider", full_name="NathanKrupa/grantspider")


def raw(number: int, **overrides) -> dict:
    """One GraphQL issue node, as the board's issue query asks for it."""
    labels = overrides.pop("labels", ())
    base = {
        "number": number,
        "title": f"issue {number}",
        "url": f"https://github.com/NathanKrupa/grantspider/issues/{number}",
        "state": "OPEN",
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-10T00:00:00Z",
        "closedAt": None,
        "body": "",
        "labels": {"totalCount": len(labels), "nodes": [{"name": name} for name in labels]},
    }
    base.update(overrides)
    return base


def variables(args: list[str]) -> dict:
    """The GraphQL variables a ``gh api graphql`` argv carries; ``key[]`` collects a list."""
    found: dict = {}
    for flag, pair in zip(args[2::2], args[3::2], strict=True):
        assert flag in ("-f", "-F"), args
        key, _, value = pair.partition("=")
        if key.endswith("[]"):
            found.setdefault(key[:-2], []).append(value)
        else:
            found[key] = value
    return found


class FakeGh:
    """Answers the board's GraphQL lists a page at a time, and REST reads by number.

    ``totals`` overrides the ``totalCount`` a list reports: an int for every
    page, or a list read by page index — the shapes of a list that is short,
    or one that changed under the read. ``pages`` overrides how a list is cut
    into pages, as explicit lists of rows.
    """

    def __init__(
        self,
        open_rows=(),
        labels=(),
        closed_rows=(),
        *,
        by_number=None,
        totals=None,
        pages=None,
        page_size=client.PAGE_SIZE,
    ):
        self.lists = {
            "OPEN": list(open_rows),
            "CLOSED": list(closed_rows),
            "labels": [{"name": name} for name in labels],
        }
        self.by_number = by_number or {}
        self.totals = totals or {}
        self.pages = pages or {}
        self.page_size = page_size
        self.calls: list[list[str]] = []

    def lists_asked(self, key: str) -> list[dict]:
        return [
            variables(c)
            for c in self.calls
            if c[:2] == ["api", "graphql"] and self._key(c) == key
        ]

    @staticmethod
    def _key(args: list[str]) -> str:
        found = variables(args)
        return found["states"][0] if "states" in found else "labels"

    def _cut(self, key: str) -> list[list[dict]]:
        if key in self.pages:
            return self.pages[key]
        rows, size = self.lists[key], self.page_size
        return [rows[i : i + size] for i in range(0, len(rows), size)] or [[]]

    def __call__(self, args: list[str]):
        self.calls.append(args)
        if args[:2] == ["api", "graphql"]:
            key = self._key(args)
            pages = self._cut(key)
            index = int(variables(args).get("cursor", 0))
            total = self.totals.get(key, sum(len(page) for page in pages))
            connection = {
                "totalCount": total[index] if isinstance(total, list) else total,
                "pageInfo": {"hasNextPage": index + 1 < len(pages), "endCursor": str(index + 1)},
                "nodes": pages[index],
            }
            field = "labels" if key == "labels" else "issues"
            return {"data": {"repository": {field: connection}}}
        if args[0] == "api":
            number = int(args[1].rsplit("/", 1)[1])
            answer = self.by_number[number]
            if isinstance(answer, Exception):
                raise answer
            return answer
        raise AssertionError(f"unexpected gh call {args}")


def test_reads_open_issues_then_closed_issues_carrying_any_epic_label():
    gh = FakeGh(
        open_rows=[raw(1), raw(2, labels=["epic:x"])],
        labels=["bug", "epic:x", "epic:y"],
        closed_rows=[
            raw(3, state="CLOSED", closedAt="2026-09-05T00:00:00Z", labels=["epic:x"])
        ],
    )

    issues = read_repo(GS, run=gh)

    assert [i.number for i in issues] == [1, 2, 3]
    assert all(i.repo == "grantspider" for i in issues)
    assert issues[1].labels == frozenset({"epic:x"})
    assert issues[2].state == "CLOSED" and issues[2].closed_at is not None
    (closed,) = gh.lists_asked("CLOSED")
    assert closed["labels"] == ["epic:x", "epic:y"]
    assert "labels" not in gh.lists_asked("OPEN")[0]
    assert all(
        variables(c)["owner"] == "NathanKrupa" and variables(c)["name"] == "grantspider"
        for c in gh.calls
    )


def test_no_epic_labels_means_no_closed_read_at_all():
    gh = FakeGh(open_rows=[raw(1)], labels=["bug"])

    issues = read_repo(GS, run=gh)

    assert [i.number for i in issues] == [1]
    assert gh.lists_asked("CLOSED") == []


def test_more_open_issues_than_any_one_page_holds_are_all_read():
    gh = FakeGh(open_rows=[raw(n) for n in range(1, 540)])

    issues = read_repo(GS, run=gh)

    assert [i.number for i in issues] == list(range(1, 540))
    cursors = [asked.get("cursor") for asked in gh.lists_asked("OPEN")]
    assert cursors == [None, "1", "2", "3", "4", "5"]


def test_labels_and_closed_epic_issues_are_read_past_their_first_page():
    names = [f"area:{n}" for n in range(150)] + ["epic:late"]
    closed = [raw(n, state="CLOSED", labels=["epic:late"]) for n in range(1000, 1250)]
    gh = FakeGh(labels=names, closed_rows=closed)

    issues = read_repo(GS, run=gh)

    assert gh.lists_asked("CLOSED")[0]["labels"] == ["epic:late"]
    assert [i.number for i in issues] == list(range(1000, 1250))


@pytest.mark.parametrize("key", ["OPEN", "labels", "CLOSED"])
def test_a_list_shorter_than_github_counts_is_a_truncated_read(key):
    gh = FakeGh(
        open_rows=[raw(1)],
        labels=["epic:x"],
        closed_rows=[raw(9, state="CLOSED", labels=["epic:x"])],
        totals={key: 2},
    )

    with pytest.raises(TruncatedReadError, match="grantspider: .* read 1 rows but GitHub counts 2"):
        read_repo(GS, run=gh)


def test_a_count_that_changes_between_pages_is_a_truncated_read():
    gh = FakeGh(open_rows=[raw(n) for n in range(1, 151)], totals={"OPEN": [150, 151]})

    with pytest.raises(TruncatedReadError, match="GitHub counts 150, 151"):
        read_repo(GS, run=gh)


def test_a_row_repeated_across_pages_cannot_stand_in_for_one_never_read():
    first = [raw(n) for n in range(1, 101)]
    second = [raw(100), *(raw(n) for n in range(102, 151))]  # #101 never comes back
    gh = FakeGh(pages={"OPEN": [first, second]}, totals={"OPEN": 150})

    with pytest.raises(TruncatedReadError, match="read 149 rows but GitHub counts 150"):
        read_repo(GS, run=gh)


def test_a_list_that_never_ends_is_refused(monkeypatch):
    monkeypatch.setattr(client, "MAX_PAGES", 2)
    gh = FakeGh(open_rows=[raw(n) for n in range(1, 301)])

    with pytest.raises(TruncatedReadError, match="open issues ran past 2 pages"):
        read_repo(GS, run=gh)


def test_an_issue_whose_own_labels_overflow_their_page_is_a_truncated_read():
    crowded = raw(1, labels=["bug"])
    crowded["labels"]["totalCount"] = 101
    gh = FakeGh(open_rows=[crowded])

    with pytest.raises(TruncatedReadError, match="#1 carries more labels"):
        read_repo(GS, run=gh)


def test_graphql_errors_are_a_gh_error():
    def failing(args):
        return {"errors": [{"message": "rate limited"}], "data": None}

    with pytest.raises(GhError, match="rate limited"):
        read_repo(GS, run=failing)


def test_read_estate_keys_by_registry_id_in_the_order_given():
    from oversteward.board.client import read_estate
    from oversteward.board.models import Issue

    ag = RepoRef(id="aigranthelper", full_name="NathanKrupa/aigranthelper")
    fake = lambda repo: (Issue.from_gh(repo.id, {**raw(1), "labels": []}),)

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


def test_body_refs_of_open_epics_that_were_not_fetched_are_read_by_number():
    from oversteward.board.client import NotFoundError

    gh = FakeGh(
        open_rows=[
            epic_raw(1, body="- [x] #50\n- [x] #51\n- [ ] #2\n- [x] #52\n- [x] #53"),
            raw(2),
            epic_raw(3, body="#60", state="CLOSED", closedAt="2026-08-01T00:00:00Z"),
            raw(4, body="#61"),
        ],
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
    rest_calls = [c for c in gh.calls if c[0] == "api" and c[1] != "graphql"]
    asked = sorted(int(c[1].rsplit("/", 1)[1]) for c in rest_calls)
    assert asked == [
        50,
        51,
        52,
        53,
    ]  # not #2 (fetched), not #60 (closed epic), not #61 (not an epic)
    assert all(c[1].startswith("repos/NathanKrupa/grantspider/issues/") for c in rest_calls)


def test_a_failed_by_number_read_that_is_not_a_404_propagates():
    from oversteward.board.client import GhError

    gh = FakeGh(
        open_rows=[epic_raw(1, body="#50")],
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


def test_gh_json_turns_a_gh_that_cannot_be_run_into_a_gh_error(monkeypatch):
    from oversteward.board import client
    from oversteward.board.client import GhError, NotFoundError, gh_json

    def no_gh(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "gh")

    monkeypatch.setattr(client.subprocess, "run", no_gh)

    try:
        gh_json(["api", "repos/NathanKrupa/grantspider/issues/1"])
    except GhError as exc:
        caught = exc
    except OSError as exc:
        pytest.fail(f"an OSError escaped gh_json: {exc!r}")
    else:
        pytest.fail("gh_json returned although gh could not be run")
    assert "gh could not be run" in str(caught)
    assert "No such file or directory" in str(caught)
    assert not isinstance(caught, NotFoundError)
