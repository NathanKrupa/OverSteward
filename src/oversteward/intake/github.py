# ABOUTME: INNER connector for intake — reads open issues and writes labels through the gh CLI.
# ABOUTME: Refuses a page that fills its limit; a truncated backlog must never read as a small one.

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from oversteward.intake.labels import LabelSpec

#: Above GrantSpider's open backlog with room to grow; a full page is refused, not trusted.
OPEN_LIMIT = 1000
_FIELDS = "number,title,labels,body,createdAt,url"

Runner = Callable[[list[str]], Any]


class GhError(RuntimeError):
    """``gh`` failed — the repository could not be read or written."""


class TruncatedReadError(GhError):
    """A page came back full; the repository holds more than was read."""


def gh(args: Sequence[str], *, run: Callable[..., Any] = subprocess.run) -> str:
    proc = run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=False)
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def gh_json(args: Sequence[str], *, run: Callable[..., Any] = subprocess.run) -> Any:
    out = gh(args, run=run).strip()
    return json.loads(out) if out else []


def list_open_issues(full_name: str, *, run: Runner = gh_json) -> list[dict]:
    rows = run(
        [
            "issue", "list", "--repo", full_name, "--state", "open",
            "--json", _FIELDS, "--limit", str(OPEN_LIMIT),
        ]
    )
    if len(rows) >= OPEN_LIMIT:
        raise TruncatedReadError(
            f"{full_name}: open issues filled the page of {OPEN_LIMIT} — the read is incomplete"
        )
    return rows


def add_labels(
    full_name: str, number: int, labels: Sequence[str], *, run: Runner = gh
) -> None:
    args = ["issue", "edit", str(number), "--repo", full_name]
    for label in labels:
        args += ["--add-label", label]
    run(args)


def upsert_label(full_name: str, spec: LabelSpec, *, run: Runner = gh) -> None:
    run(
        [
            "label", "create", spec.name, "--repo", full_name,
            "--color", spec.color, "--description", spec.description, "--force",
        ]
    )
