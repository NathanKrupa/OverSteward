#!/usr/bin/env python3
# ABOUTME: Operator-steps channel — pushes steps Nathan must perform to his Todoist
# ABOUTME: "Operator Steps" project so they never get lost in a session log.
"""CLI: add, list, and complete operator steps in Todoist.

Doctrine (OS#, 2026-08-19, Nathan's order): whenever a session surfaces a step
only Nathan can perform — a secret to mint, a settings paste, a dashboard
click, an approval — it MUST also be pushed here, and marked done when the
step is verified complete. The session log is not a to-do list.

The token is read in-process from the ai-assistants context's .env
(`TODOIST_API_KEY`), the one place it is provisioned; never printed.

Usage:
    operator_steps.py add "Paste the autoMode block into settings.json" \
        --description "…full instructions…" [--due tomorrow] [--priority 3]
    operator_steps.py list
    operator_steps.py done <task-id>
"""

from __future__ import annotations

import argparse
import sys

import requests

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - environment guard, not logic
    sys.exit("python-dotenv required (run via a project venv that has it)")

_TOKEN_ENV_PATH = "/home/natha/ai-assistants/.env"
_TOKEN_KEY = "TODOIST_API_KEY"
_API = "https://api.todoist.com/api/v1"
_PROJECT_NAME = "Operator Steps"
_TIMEOUT = 15


def _headers() -> dict[str, str]:
    token = (dotenv_values(_TOKEN_ENV_PATH).get(_TOKEN_KEY) or "").strip()
    if not token:
        sys.exit(f"{_TOKEN_KEY} not found in {_TOKEN_ENV_PATH}")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _project_id(headers: dict[str, str]) -> str:
    resp = requests.get(f"{_API}/projects", headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("results", payload if isinstance(payload, list) else [])
    for project in rows:
        if project.get("name") == _PROJECT_NAME:
            return project["id"]
    resp = requests.post(
        f"{_API}/projects",
        headers=headers,
        json={"name": _PROJECT_NAME, "color": "red"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def cmd_add(args: argparse.Namespace) -> None:
    headers = _headers()
    body: dict[str, object] = {
        "content": args.content,
        "project_id": _project_id(headers),
        "priority": args.priority,
    }
    if args.description:
        body["description"] = args.description
    if args.due:
        body["due_string"] = args.due
    resp = requests.post(f"{_API}/tasks", headers=headers, json=body, timeout=_TIMEOUT)
    resp.raise_for_status()
    task = resp.json()
    print(f"added {task['id']}: {task['content']}")


def cmd_list(_: argparse.Namespace) -> None:
    headers = _headers()
    resp = requests.get(
        f"{_API}/tasks",
        headers=headers,
        params={"project_id": _project_id(headers)},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("results", payload if isinstance(payload, list) else [])
    if not rows:
        print("no open operator steps")
        return
    for task in rows:
        due = (task.get("due") or {}).get("date", "")
        print(f"{task['id']}  {task['content']}" + (f"  (due {due})" if due else ""))


def cmd_done(args: argparse.Namespace) -> None:
    resp = requests.post(
        f"{_API}/tasks/{args.task_id}/close", headers=_headers(), timeout=_TIMEOUT
    )
    resp.raise_for_status()
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
