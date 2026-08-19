#!/usr/bin/env python3
# ABOUTME: Operator-steps channel — pushes steps Nathan must perform to his Todoist
# ABOUTME: "Operator Steps" project so they never get lost in a session log.
"""CLI: add, list, and complete operator steps in Todoist.

Doctrine (Nathan's order, 2026-08-19): whenever a session surfaces a step only
Nathan can perform — a secret to mint, a settings paste, a dashboard click, an
approval — it MUST also be pushed here, and marked done when the step is
verified complete. The session log is not a to-do list.

Stdlib-only (urllib), like every canonical shared script, so it runs from any
repo's venv or bare python3. The token is read in-process from the
ai-assistants context's .env (`TODOIST_API_KEY`), the one place it is
provisioned; never printed.

Usage:
    operator_steps.py add "Paste the autoMode block into settings.json" \
        --description "…full instructions…" [--due tomorrow] [--priority 3]
    operator_steps.py list
    operator_steps.py done <task-id>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

_TOKEN_ENV_PATH = "/home/natha/ai-assistants/.env"
_TOKEN_KEY = "TODOIST_API_KEY"
_API = "https://api.todoist.com/api/v1"
_PROJECT_NAME = "Operator Steps"
_TIMEOUT = 15


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


def _rows(payload) -> list[dict]:
    """v1 endpoints wrap collections as {"results": [...]}; tolerate both shapes."""
    if isinstance(payload, dict):
        return payload.get("results", [])
    return payload


def _project_id() -> str:
    for project in _rows(_request("GET", "/projects")):
        if project.get("name") == _PROJECT_NAME:
            return project["id"]
    return _request("POST", "/projects", body={"name": _PROJECT_NAME, "color": "red"})["id"]


def cmd_add(args: argparse.Namespace) -> None:
    body: dict[str, object] = {
        "content": args.content,
        "project_id": _project_id(),
        "priority": args.priority,
    }
    if args.description:
        body["description"] = args.description
    if args.due:
        body["due_string"] = args.due
    task = _request("POST", "/tasks", body=body)
    print(f"added {task['id']}: {task['content']}")


def cmd_list(_: argparse.Namespace) -> None:
    rows = _rows(_request("GET", "/tasks", query={"project_id": _project_id()}))
    if not rows:
        print("no open operator steps")
        return
    for task in rows:
        due = (task.get("due") or {}).get("date", "")
        print(f"{task['id']}  {task['content']}" + (f"  (due {due})" if due else ""))


def cmd_done(args: argparse.Namespace) -> None:
    _request("POST", f"/tasks/{args.task_id}/close")
    print(f"done {args.task_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="push an operator step to Nathan's Todoist")
    add.add_argument("content")
    add.add_argument("--description", default="")
    add.add_argument("--due", default=None)
    add.add_argument("--priority", type=int, default=3, choices=(1, 2, 3, 4))
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="list open operator steps")
    lst.set_defaults(func=cmd_list)

    done = sub.add_parser("done", help="mark an operator step complete (verified)")
    done.add_argument("task_id")
    done.set_defaults(func=cmd_done)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
