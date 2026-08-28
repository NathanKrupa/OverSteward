# ABOUTME: INNER connectors — one class per external system: git, gh, the target repo's ruff, make, the lock.
# ABOUTME: No decisions here; each maps a command's exit status onto a CommandResult the service reads.

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

#: Every command is argv, never a shell string — a repo path with a space in it
#: must not become two arguments, and nothing sow runs is ever concatenated.
_CAPTURE = {"capture_output": True, "text": True}


class SowError(RuntimeError):
    """A step sow attempted could not be completed. Always names what failed."""


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    out: str
    err: str

    @property
    def text(self) -> str:
        return (self.out + self.err).strip()


def _run(argv: list[str], cwd: Path) -> CommandResult:
    proc = subprocess.run(argv, cwd=str(cwd), check=False, **_CAPTURE)
    return CommandResult(proc.returncode == 0, proc.stdout, proc.stderr)


class GitCommand:
    """Runs git in a named directory."""

    def run(self, cwd: Path, *args: str) -> CommandResult:
        return _run(["git", *args], cwd)


class GhCommand:
    """Talks to GitHub through the `gh` CLI, which owns the credential."""

    def open_sync_branches(self, cwd: Path, prefix: str) -> tuple[str, ...] | None:
        """Open sync branches on this repo, or None when the list could not be read.

        None is not an empty list: a gh that cannot answer must never read as
        "no prior sync PR", or sow stacks a second one on top.
        """
        result = _run(
            ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "headRefName"], cwd
        )
        if not result.ok:
            return None
        try:
            listed = json.loads(result.out)
        except json.JSONDecodeError:
            return None
        return tuple(
            str(pr.get("headRefName", ""))
            for pr in listed
            if str(pr.get("headRefName", "")).startswith(prefix)
        )

    def create_pr(self, cwd: Path, base: str, head: str, title: str, body_path: Path) -> str:
        result = _run(
            [
                "gh", "pr", "create",
                "--base", base,
                "--head", head,
                "--title", title,
                "--body-file", str(body_path),
            ],
            cwd,
        )
        if not result.ok:
            raise SowError(f"gh pr create failed: {result.text}")
        url = next((line for line in reversed(result.out.splitlines()) if line.strip()), "")
        if not url.startswith("http"):
            raise SowError(f"gh pr create printed no pull request URL: {result.text}")
        return url.strip()


class RuffCommand:
    """The TARGET repo's own ruff, so its pyproject decides — never OverSteward's."""

    def _binary(self, repo_root: Path) -> Path:
        return repo_root / ".venv" / "bin" / "ruff"

    def available(self, repo_root: Path) -> bool:
        return self._binary(repo_root).is_file()

    def objections(
        self, repo_root: Path, worktree: Path, relpaths: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Whatever the target's formatter and linter say about the copied bytes.

        `--force-exclude` is what makes the answer meaningful: without it the
        repo's `extend-exclude` is ignored for explicitly-named paths, so an
        excluded family member would be judged anyway and every repo would look
        like it needed a fix it already has.
        """
        ruff = str(self._binary(repo_root))
        findings: list[str] = []
        for argv in (
            [ruff, "format", "--check", "--force-exclude", *relpaths],
            [ruff, "check", "--force-exclude", *relpaths],
        ):
            result = _run(argv, worktree)
            if not result.ok:
                findings.extend(line for line in result.text.splitlines() if line.strip())
        return tuple(findings)


class MakeCommand:
    """The target repo's `make verify`, written to a log file rather than a pipe.

    Never `| tail` — a pipeline reports the filter's exit status, so a failing
    verify would read as a pass (pr-workflow.md § False greens).
    """

    def verify(self, worktree: Path, log_path: Path) -> CommandResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["make", "verify"], cwd=str(worktree), check=False, **_CAPTURE)
        log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        return CommandResult(proc.returncode == 0, proc.stdout, proc.stderr)


class SowLock:
    """One sow run at a time, per machine. Atomic O_EXCL create; released on exit."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._fd: int | None = None

    @property
    def acquired(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        os.write(self._fd, f"{os.getpid()}\n".encode())
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        os.close(self._fd)
        self._fd = None
        self._path.unlink(missing_ok=True)

    def __enter__(self) -> SowLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
