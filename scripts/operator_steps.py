#!/usr/bin/env python3
# ABOUTME: Operator-steps channel — pushes steps Nathan must perform to his Todoist
# ABOUTME: "Operator Steps" project so they never get lost in a session log.
"""CLI: add, list, number and complete operator steps in Todoist.

Doctrine (Nathan's order, 2026-08-19): whenever a session surfaces a step only
Nathan can perform — a secret to mint, a settings paste, a dashboard click, an
approval — it MUST also be pushed here, and marked done when the step is
verified complete. The session log is not a to-do list.

Every step carries a reference number at the front of its content — ``TD12:
Paste the autoMode block`` — so Nathan can name it in chat ("TD12 is done").
The number is one past the highest TD number Todoist still holds for the
project, open steps and completed history alike; nothing is kept locally.
Close steps, never delete them — a deleted step's number would come back —
and `done` refuses a reference that names more than one open step.

Stdlib-only (urllib), like every canonical shared script, so it runs from any
repo's venv or bare python3. The token is read in-process from the
ai-assistants context's .env (`TODOIST_API_KEY`), the one place it is
provisioned; never printed.

Usage:
    operator_steps.py add "Paste the autoMode block into settings.json" \
        --description "…full instructions…" [--due tomorrow] [--priority 3]
    operator_steps.py list
    operator_steps.py number          # give any unnumbered open step a TD number
    operator_steps.py done TD12
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_TOKEN_ENV_PATH = "/home/natha/ai-assistants/.env"
_TOKEN_KEY = "TODOIST_API_KEY"
_API = "https://api.todoist.com/api/v1"
_PROJECT_NAME = "Operator Steps"
_TIMEOUT = 15
_ISO = "%Y-%m-%dT%H:%M:%SZ"
# The completed-tasks endpoint refuses a window wider than about three months.
_COMPLETED_WINDOW = dt.timedelta(days=90)
_PAGE = 200
_TD_PREFIX = re.compile(r"^TD(\d+)\b", re.IGNORECASE)
_TD_REF = re.compile(r"^(?:TD\s*)?(\d+)$", re.IGNORECASE)


def _token() -> str:
    """Parse the .env in-process; only the one key is read, nothing printed."""
    try:
        with open(_TOKEN_ENV_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"{_TOKEN_KEY}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError as exc:
        sys.exit(f"cannot read {_TOKEN_ENV_PATH}: {exc}")
    sys.exit(f"{_TOKEN_KEY} not found in {_TOKEN_ENV_PATH}")


def _request(method: str, path: str, body: dict | None = None, query: dict | None = None):
    url = f"{_API}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"Todoist {method} {path} failed: HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"Todoist unreachable: {exc.reason}")
    return json.loads(raw) if raw else {}


def _paged(path: str, query: dict | None = None, key: str = "results") -> list[dict]:
    """Every v1 collection endpoint pages by next_cursor; read the whole collection."""
    query = {**(query or {}), "limit": _PAGE}
    rows: list[dict] = []
    while True:
        page = _request("GET", path, query=query)
        rows.extend(page.get(key, []))
        cursor = page.get("next_cursor")
        if not cursor:
            return rows
        query = {**query, "cursor": cursor}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime(_ISO)


def _project() -> dict:
    """The Operator Steps project, created if absent.

    A project created here dates from now — it has no history to read — so the
    create response is not relied on to carry created_at.
    """
    for project in _paged("/projects"):
        if project.get("name") == _PROJECT_NAME:
            return project
    created = _request("POST", "/projects", body={"name": _PROJECT_NAME, "color": "red"})
    return {**created, "created_at": created.get("created_at") or _now_iso()}


def _open_tasks(project_id: str) -> list[dict]:
    return _paged("/tasks", {"project_id": project_id})


def _td_number(content: str) -> int | None:
    """The TD number a task's content leads with, or None when it carries none."""
    match = _TD_PREFIX.match(content)
    return int(match.group(1)) if match else None


def _strip_prefix(content: str) -> str:
    return _TD_PREFIX.sub("", content).lstrip(": ").strip()


def _parse_ref(ref: str) -> int:
    """A reference as Nathan types it — TD12, td12, TD 12 or bare 12 — as its number."""
    match = _TD_REF.match(ref.strip())
    if not match or int(match.group(1)) < 1:
        sys.exit(f"not a TD reference: {ref!r} (expected e.g. TD12)")
    return int(match.group(1))


def _completed_numbers(project: dict) -> list[int]:
    """TD numbers of every completed step, in windows from the project's creation."""
    if not project.get("created_at"):
        sys.exit(f"{_PROJECT_NAME} project payload carries no created_at; cannot read history")
    numbers: list[int] = []
    since = dt.datetime.fromisoformat(project["created_at"]).replace(microsecond=0)
    now = dt.datetime.strptime(_now_iso(), _ISO).replace(tzinfo=dt.timezone.utc)
    while since < now:
        until = min(since + _COMPLETED_WINDOW, now)
        query = {
            "project_id": project["id"],
            "since": since.strftime(_ISO),
            "until": until.strftime(_ISO),
        }
        rows = _paged("/tasks/completed/by_completion_date", query, key="items")
        numbers.extend(n for n in (_td_number(t.get("content", "")) for t in rows) if n)
        since = until
    return numbers


def _next_number(project: dict | None = None) -> int:
    project = project or _project()
    open_numbers = [n for n in (_td_number(t["content"]) for t in _open_tasks(project["id"])) if n]
    return max([0, *open_numbers, *_completed_numbers(project)]) + 1


def cmd_add(args: argparse.Namespace) -> None:
    project = _project()
    body: dict[str, object] = {
        "content": f"TD{_next_number(project)}: {args.content}",
        "project_id": project["id"],
        "priority": args.priority,
    }
    if args.description:
        body["description"] = args.description
    if args.due:
        body["due_string"] = args.due
    task = _request("POST", "/tasks", body=body)
    print(f"added {task['content']}")


def cmd_list(_: argparse.Namespace) -> None:
    rows = _open_tasks(_project()["id"])
    if not rows:
        print("no open operator steps")
        return
    numbered = sorted(
        (t for t in rows if _td_number(t["content"])), key=lambda t: _td_number(t["content"])
    )
    unnumbered = [t for t in rows if not _td_number(t["content"])]
    for task in numbered:
        due = (task.get("due") or {}).get("date", "")
        ref = f"TD{_td_number(task['content'])}"
        print(f"{ref:<6}{_strip_prefix(task['content'])}" + (f"  (due {due})" if due else ""))
    for task in unnumbered:
        print(f"{'--':<6}{task['content']}")
    if unnumbered:
        noun = "task lacks" if len(unnumbered) == 1 else "tasks lack"
        print(f"{len(unnumbered)} {noun} a TD number — run: operator_steps.py number")


def cmd_number(_: argparse.Namespace) -> None:
    project = _project()
    rows = _open_tasks(project["id"])
    unnumbered = sorted(
        (t for t in rows if not _td_number(t["content"])), key=lambda t: t.get("created_at", "")
    )
    if not unnumbered:
        print(f"all {len(rows)} open steps carry a TD number")
        return
    number = _next_number(project)
    for task in unnumbered:
        content = f"TD{number}: {task['content']}"
        _request("POST", f"/tasks/{task['id']}", body={"content": content})
        print(content)
        number += 1


def cmd_done(args: argparse.Namespace) -> None:
    number = _parse_ref(args.ref)
    matches = [t for t in _open_tasks(_project()["id"]) if _td_number(t["content"]) == number]
    if len(matches) > 1:
        sys.exit(
            f"TD{number} names {len(matches)} open steps — close the duplicate in Todoist "
            "by hand before marking either done"
        )
    if not matches:
        sys.exit(
            f"TD{number} is not an open operator step — already done, or never numbered "
            "(run: operator_steps.py number)"
        )
    task = matches[0]
    _request("POST", f"/tasks/{task['id']}/close")
    print(f"done TD{number}: {_strip_prefix(task['content'])}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="push an operator step to Nathan's Todoist")
    add.add_argument("content")
    add.add_argument("--description", default="")
    add.add_argument("--due", default=None)
    add.add_argument("--priority", type=int, default=3, choices=(1, 2, 3, 4))
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="list open operator steps by TD number")
    lst.set_defaults(func=cmd_list)

    number = sub.add_parser("number", help="give every unnumbered open step a TD number")
    number.set_defaults(func=cmd_number)

    done = sub.add_parser("done", help="mark an operator step complete (verified), by TD number")
    done.add_argument("ref", help="the step's reference, e.g. TD12")
    done.set_defaults(func=cmd_done)

    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()
