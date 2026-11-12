# ABOUTME: INNER connector for ci_red rerun — reads a workflow and its runs, writes a branch ref,
# ABOUTME: and dispatches a workflow on it, all through `gh api`.

"""The GitHub Actions and git-refs calls ``ci_red.py rerun`` makes.

Every call goes through ``gh api`` (an injected runner). A failure is
:class:`SourceUnavailableError`, with one exception the caller relies on: a
branch ref that GitHub answers ``404`` for is *absent*, not unreadable, so a ref
already gone reads as done.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from oversteward.intake.github import GhError, gh, gh_json

from .sources import Runner, SourceUnavailableError

#: One page of a workflow's dispatched runs on a branch; a full page is refused, not trusted.
RUN_PAGE = 100
_NOT_FOUND = "(HTTP 404)"


class GithubWorkflows:
    """One repository's workflows, runs and branch refs, as ``rerun`` reads and writes them."""

    def __init__(self, *, run_json: Runner = gh_json, run: Runner = gh) -> None:
        self._json = run_json
        self._run = run

    def _read(self, args: list[str]) -> Any:
        try:
            return self._json(["api", *args])
        except GhError as exc:
            raise SourceUnavailableError(str(exc)) from exc

    def _write(self, args: list[str]) -> None:
        try:
            self._run(["api", *args])
        except GhError as exc:
            raise SourceUnavailableError(str(exc)) from exc

    def workflow_path(self, full_name: str, workflow_id: int) -> str:
        row = self._read([f"repos/{full_name}/actions/workflows/{workflow_id}"])
        path = row.get("path") if isinstance(row, dict) else None
        if not isinstance(path, str) or not path:
            raise SourceUnavailableError(f"{full_name}: workflow {workflow_id} names no path")
        return path

    def file_at(self, full_name: str, path: str, sha: str) -> bytes:
        row = self._read([f"repos/{full_name}/contents/{path}?ref={sha}"])
        content = row.get("content") if isinstance(row, dict) else None
        if not isinstance(content, str) or row.get("encoding") != "base64":
            raise SourceUnavailableError(f"{full_name}: {path} at {sha} came back without content")
        try:
            return base64.b64decode(content)
        except binascii.Error as exc:
            raise SourceUnavailableError(f"{full_name}: {path} at {sha} is not base64") from exc

    def ref_sha(self, full_name: str, branch: str) -> str | None:
        """The commit ``refs/heads/<branch>`` points at, or ``None`` when it does not exist."""
        try:
            row = self._json(["api", f"repos/{full_name}/git/ref/heads/{branch}"])
        except GhError as exc:
            if _NOT_FOUND in str(exc):
                return None
            raise SourceUnavailableError(str(exc)) from exc
        obj = row.get("object") if isinstance(row, dict) else None
        sha = obj.get("sha") if isinstance(obj, dict) else None
        if not isinstance(sha, str) or not sha:
            raise SourceUnavailableError(f"{full_name}: ref {branch} came back without a sha")
        return sha

    def create_ref(self, full_name: str, branch: str, sha: str) -> None:
        self._write(
            [
                "-X", "POST", f"repos/{full_name}/git/refs",
                "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}",
            ]
        )

    def delete_ref(self, full_name: str, branch: str) -> None:
        self._write(["-X", "DELETE", f"repos/{full_name}/git/refs/heads/{branch}"])

    def dispatch(self, full_name: str, workflow_id: int, branch: str) -> None:
        self._write(
            [
                "-X", "POST", f"repos/{full_name}/actions/workflows/{workflow_id}/dispatches",
                "-f", f"ref={branch}",
            ]
        )

    def dispatched_runs(
        self, full_name: str, workflow_id: int, branch: str
    ) -> tuple[tuple[int, str], ...]:
        """Every ``workflow_dispatch`` run of the workflow on ``branch``: ``(run id, head sha)``."""
        row = self._read(
            [
                f"repos/{full_name}/actions/workflows/{workflow_id}/runs"
                f"?branch={branch}&event=workflow_dispatch&per_page={RUN_PAGE}"
            ]
        )
        runs = row.get("workflow_runs") if isinstance(row, dict) else None
        if not isinstance(runs, list):
            raise SourceUnavailableError(f"{full_name}: workflow {workflow_id} runs unreadable")
        if len(runs) >= RUN_PAGE:
            raise SourceUnavailableError(
                f"{full_name}: runs on {branch} filled the page of {RUN_PAGE}"
            )
        return tuple(
            (run["id"], str(run.get("head_sha") or ""))
            for run in runs
            if isinstance(run, dict) and isinstance(run.get("id"), int)
        )
