# ABOUTME: Tests for scripts/operator_steps.py — TD reference numbers on Todoist operator steps.
# ABOUTME: Covers allocation over open+completed history, add/list/done/number verbs, TD ref parsing.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT = {
    "id": "proj-1",
    "name": "Operator Steps",
    "created_at": "2026-08-19T12:27:47.105056Z",
}


def _load_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "operator_steps.py"
    spec = importlib.util.spec_from_file_location("oversteward_operator_steps", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ops():
    return _load_module()


class FakeTodoist:
    """Records every request; serves projects, open tasks and completed windows."""

    def __init__(self, open_tasks, completed_by_window=None):
        self.open_tasks = open_tasks
        self.completed_by_window = completed_by_window or {}
        self.calls: list[tuple] = []

    def __call__(self, method, path, body=None, query=None):
        self.calls.append((method, path, body, query))
        if method == "GET" and path == "/projects":
            return {"results": [_PROJECT]}
        if method == "GET" and path == "/tasks":
            return {"results": list(self.open_tasks)}
        if method == "GET" and path == "/tasks/completed/by_completion_date":
            return {"items": self.completed_by_window.get(query["since"], [])}
        if method == "POST" and path == "/tasks":
            task = {"id": f"new-{len(self.calls)}", **body}
            self.open_tasks.append(task)
            return task
        if method == "POST" and path.startswith("/tasks/") and path.endswith("/close"):
            return {}
        if method == "POST" and path.startswith("/tasks/"):
            task_id = path.removeprefix("/tasks/")
            for task in self.open_tasks:
                if task["id"] == task_id:
                    task.update(body)
                    return task
        raise AssertionError(f"unexpected request {method} {path}")


def _task(task_id, content, created_at="2026-09-01T00:00:00Z", due=None):
    task = {"id": task_id, "content": content, "created_at": created_at}
    if due:
        task["due"] = {"date": due}
    return task


@pytest.fixture
def fake(ops, monkeypatch):
    def install(open_tasks, completed_by_window=None):
        api = FakeTodoist(open_tasks, completed_by_window)
        monkeypatch.setattr(ops, "_request", api)
        return api

    return install


# --- TD reference parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("TD12: Paste the block", 12),
        ("td7: lower case still counts", 7),
        ("TD3 no colon", 3),
        ("Paste TD12 into settings", None),
        ("TDX: not a number", None),
        ("", None),
    ],
)
def test_td_number_reads_only_a_leading_prefix(ops, content, expected):
    assert ops._td_number(content) == expected


@pytest.mark.parametrize("ref", ["TD12", "td12", "TD 12", "12"])
def test_parse_ref_accepts_the_forms_nathan_types(ops, ref):
    assert ops._parse_ref(ref) == 12


@pytest.mark.parametrize("ref", ["TD", "TDabc", "6hJ85VQqc6rCWmhX", "TD0", ""])
def test_parse_ref_rejects_ids_and_junk(ops, ref):
    with pytest.raises(SystemExit):
        ops._parse_ref(ref)


# --- allocation -----------------------------------------------------------------------


def test_next_number_starts_at_one_on_an_empty_project(ops, fake):
    fake([])
    assert ops._next_number() == 1


def test_next_number_is_one_past_the_highest_open_number(ops, fake):
    fake([_task("a", "TD4: x"), _task("b", "TD9: y"), _task("c", "unnumbered")])
    assert ops._next_number() == 10


def test_next_number_counts_completed_tasks_so_a_retired_number_is_never_reused(
    ops, fake, monkeypatch
):
    monkeypatch.setattr(ops, "_now_iso", lambda: "2026-09-13T00:00:00Z")
    fake(
        [_task("a", "TD4: open")],
        completed_by_window={"2026-08-19T12:27:47Z": [{"content": "TD11: closed last week"}]},
    )
    assert ops._next_number() == 12


def test_completed_history_is_paged_in_90_day_windows_from_project_creation(ops, fake, monkeypatch):
    monkeypatch.setattr(ops, "_now_iso", lambda: "2027-03-01T00:00:00Z")
    api = fake([], completed_by_window={"2026-11-17T12:27:47Z": [{"content": "TD40: old"}]})
    assert ops._next_number() == 41
    windows = [
        (q["since"], q["until"])
        for _, path, _, q in api.calls
        if path == "/tasks/completed/by_completion_date"
    ]
    assert windows == [
        ("2026-08-19T12:27:47Z", "2026-11-17T12:27:47Z"),
        ("2026-11-17T12:27:47Z", "2027-02-15T12:27:47Z"),
        ("2027-02-15T12:27:47Z", "2027-03-01T00:00:00Z"),
    ]
    assert all(q["project_id"] == "proj-1" for _, path, _, q in api.calls if "completed" in path)


# --- verbs ----------------------------------------------------------------------------


def test_add_prefixes_content_with_the_next_number(ops, fake, capsys):
    api = fake([_task("a", "TD22: last")])
    ops.cmd_add(ops._parse_args(["add", "Mint the token", "--description", "how"]))
    created = [b for m, p, b, _ in api.calls if (m, p) == ("POST", "/tasks")]
    assert created == [
        {
            "content": "TD23: Mint the token",
            "project_id": "proj-1",
            "priority": 3,
            "description": "how",
        }
    ]
    assert capsys.readouterr().out == "added TD23: Mint the token\n"


def test_list_shows_td_refs_and_flags_unnumbered_tasks(ops, fake, capsys):
    fake(
        [
            _task("a", "TD5: five", due="2026-09-15"),
            _task("b", "no number yet"),
            _task("c", "TD2: two"),
        ]
    )
    ops.cmd_list(ops._parse_args(["list"]))
    assert capsys.readouterr().out == (
        "TD2   two\n"
        "TD5   five  (due 2026-09-15)\n"
        "--    no number yet\n"
        "1 task lacks a TD number — run: operator_steps.py number\n"
    )


def test_done_resolves_a_td_ref_to_the_open_task_and_closes_it(ops, fake, capsys):
    api = fake([_task("a", "TD5: five"), _task("b", "TD6: six")])
    ops.cmd_done(ops._parse_args(["done", "td6"]))
    assert ("POST", "/tasks/b/close", None, None) in api.calls
    assert capsys.readouterr().out == "done TD6: six\n"


def test_done_refuses_an_unknown_or_already_closed_ref(ops, fake):
    api = fake([_task("a", "TD5: five")])
    with pytest.raises(SystemExit, match="TD9"):
        ops.cmd_done(ops._parse_args(["done", "TD9"]))
    assert not any(p.endswith("/close") for _, p, _, _ in api.calls)


def test_number_assigns_refs_to_unnumbered_tasks_in_creation_order(ops, fake, capsys, monkeypatch):
    monkeypatch.setattr(ops, "_now_iso", lambda: "2026-09-13T00:00:00Z")
    api = fake(
        [
            _task("late", "added later", created_at="2026-09-10T00:00:00Z"),
            _task("num", "TD3: already numbered"),
            _task("early", "added first", created_at="2026-08-20T00:00:00Z"),
        ],
        completed_by_window={"2026-08-19T12:27:47Z": [{"content": "TD7: closed"}]},
    )
    ops.cmd_number(ops._parse_args(["number"]))
    updates = [(p, b) for m, p, b, _ in api.calls if m == "POST" and not p.endswith("/close")]
    assert updates == [
        ("/tasks/early", {"content": "TD8: added first"}),
        ("/tasks/late", {"content": "TD9: added later"}),
    ]
    assert capsys.readouterr().out == "TD8: added first\nTD9: added later\n"


def test_number_is_idempotent_when_everything_is_numbered(ops, fake, capsys):
    api = fake([_task("a", "TD1: one")])
    ops.cmd_number(ops._parse_args(["number"]))
    assert not any(m == "POST" for m, _, _, _ in api.calls)
    assert capsys.readouterr().out == "all 1 open steps carry a TD number\n"


def test_completed_history_follows_the_cursor_within_a_window(ops, fake, monkeypatch):
    monkeypatch.setattr(ops, "_now_iso", lambda: "2026-09-13T00:00:00Z")
    api = fake([])
    pages = {
        None: {"items": [{"content": "TD3: first page"}], "next_cursor": "c2"},
        "c2": {"items": [{"content": "TD50: second page"}], "next_cursor": None},
    }
    api_call = api.__call__

    def with_cursor(method, path, body=None, query=None):
        if path == "/tasks/completed/by_completion_date":
            api.calls.append((method, path, body, query))
            return pages[query.get("cursor")]
        return api_call(method, path, body, query)

    monkeypatch.setattr(ops, "_request", with_cursor)
    assert ops._next_number() == 51
    cursors = [q.get("cursor") for _, p, _, q in api.calls if "completed" in p]
    assert cursors == [None, "c2"]


def test_done_refuses_when_two_open_steps_carry_the_same_number(ops, fake):
    api = fake([_task("real", "TD51: mint the token"), _task("dup", "TD51: paste the block")])
    with pytest.raises(SystemExit, match="TD51"):
        ops.cmd_done(ops._parse_args(["done", "TD51"]))
    assert not any(p.endswith("/close") for _, p, _, _ in api.calls)


def test_open_tasks_and_projects_follow_the_cursor_past_the_first_page(ops, monkeypatch):
    calls = []
    pages = {
        ("/projects", None): {"results": [{"id": "x", "name": "Inbox"}], "next_cursor": "p2"},
        ("/projects", "p2"): {"results": [_PROJECT], "next_cursor": None},
        ("/tasks", None): {"results": [_task("a", "TD1: one")], "next_cursor": "t2"},
        ("/tasks", "t2"): {"results": [_task("b", "TD60: on page two")], "next_cursor": None},
        ("/tasks/completed/by_completion_date", None): {"items": []},
    }

    def paged(method, path, body=None, query=None):
        calls.append((method, path, query))
        return pages[(path, (query or {}).get("cursor"))]

    monkeypatch.setattr(ops, "_request", paged)
    monkeypatch.setattr(ops, "_now_iso", lambda: "2026-09-13T00:00:00Z")
    assert ops._next_number() == 61
    assert [q.get("cursor") for m, p, q in calls if p == "/projects"] == [None, "p2"]
    assert [q.get("cursor") for m, p, q in calls if p == "/tasks"] == [None, "t2"]
    assert all(q.get("limit") == 200 for m, p, q in calls if p in ("/projects", "/tasks"))


def test_a_freshly_created_project_allocates_from_now_without_a_created_at(ops, monkeypatch):
    calls = []

    def creating(method, path, body=None, query=None):
        calls.append((method, path, query))
        if (method, path) == ("GET", "/projects"):
            return {"results": []}
        if (method, path) == ("POST", "/projects"):
            return {"id": "new-proj", "name": "Operator Steps"}
        if (method, path) == ("GET", "/tasks"):
            return {"results": []}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(ops, "_request", creating)
    assert ops._next_number() == 1
    assert ("POST", "/projects", None) in calls
    assert not any("completed" in p for _, p, _ in calls)


def test_a_found_project_without_created_at_fails_loudly_rather_than_skipping_history(
    ops, monkeypatch
):
    calls = []

    def found_but_bare(method, path, body=None, query=None):
        calls.append((method, path))
        if (method, path) == ("GET", "/projects"):
            return {"results": [{"id": "proj-1", "name": "Operator Steps"}]}
        if (method, path) == ("GET", "/tasks"):
            return {"results": [_task("a", "TD2: open")]}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(ops, "_request", found_but_bare)
    with pytest.raises(SystemExit, match="created_at"):
        ops._next_number()
    assert ("POST", "/projects") not in calls
