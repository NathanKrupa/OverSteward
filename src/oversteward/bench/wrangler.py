# ABOUTME: INNER connector for Cloudflare Pages — one direct upload of a directory through `wrangler pages deploy`.
# ABOUTME: Transport only: credentials go in the child's environment, never argv; the caller decides what to upload.

"""Upload a directory to a Pages project.

The CLI is the estate's standard connection (cli-connection-standard.md), and
wrangler is the one client that computes the asset hashes Pages expects, so
the upload is delegated to it rather than reimplemented over the REST
direct-upload flow. It runs from a scratch directory: wrangler writes a config
cache under ``node_modules/.cache`` in its working directory, which must never
land inside the tree being published.

Success is read off wrangler's own completion lines, not its exit code alone:
it exits 0 when it "couldn't ascertain the final status" of a deployment, and
that is not a publish.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from oversteward.bench.config import PagesCredentials

#: Uploads can carry hundreds of rendered pages; wrangler polls the deployment after them.
_TIMEOUT_SECONDS = 600

#: Fetched into the npx cache on first use; pinned to the major so the output lines below stay stable.
DEFAULT_WRANGLER: tuple[str, ...] = ("npx", "--yes", "wrangler@4")

#: wrangler's two completion lines (pages/deploy, on `latest_stage == deploy/success`).
_DEPLOYMENT_URL = re.compile(r"Deployment complete! Take a peek over at (https://\S+)")
_ALIAS_URL = re.compile(r"Deployment alias URL: (https://\S+)")

#: wrangler colours its stderr even when captured.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: wrangler's error line and the trailer it always ends on.
_ERROR_MARK = "[ERROR]"
_LOG_TRAILER = "Logs were written to"
_ISSUE_NUDGE = "If you think this is a bug"

Runner = Callable[..., subprocess.CompletedProcess]


class UploadError(RuntimeError):
    """The upload did not happen, or wrangler could not confirm that it did."""


@dataclass(frozen=True, slots=True)
class Deployment:
    """Where the upload landed: the immutable deployment URL, and the branch alias when Pages made one."""

    url: str
    alias: str | None = None


def deploy(
    directory: Path,
    *,
    credentials: PagesCredentials,
    branch: str,
    run: Runner = subprocess.run,
    wrangler: Sequence[str] = DEFAULT_WRANGLER,
) -> Deployment:
    """Upload ``directory`` to the credentials' project on ``branch`` and return where it landed."""
    # Absolute: the child runs from a scratch cwd, where a caller-relative path does not exist.
    command = [
        *wrangler, "pages", "deploy", str(directory.resolve()),
        "--project-name", credentials.project, "--branch", branch, "--commit-dirty=true",
    ]
    env = {
        **os.environ,
        "CLOUDFLARE_API_TOKEN": credentials.token,
        "CLOUDFLARE_ACCOUNT_ID": credentials.account_id,
        "WRANGLER_SEND_METRICS": "false",
        "CI": "true",
    }
    with tempfile.TemporaryDirectory(prefix="design-bench-") as scratch:
        completed = _run(run, command, env=env, cwd=scratch)
    return _deployment_of(completed.stdout or "")


def _run(run: Runner, command: list[str], *, env: dict[str, str], cwd: str) -> subprocess.CompletedProcess:
    """Execute wrangler; never echo argv, stdin or the environment on failure."""
    try:
        completed = run(
            command, env=env, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise UploadError(f"{command[0]} not found on PATH — wrangler runs through npx (node)") from None
    except subprocess.TimeoutExpired:
        raise UploadError(f"wrangler did not finish within {_TIMEOUT_SECONDS}s") from None
    if completed.returncode != 0:
        raise UploadError(f"wrangler exited {completed.returncode}: {_failure_detail(completed.stderr, completed.stdout)}")
    return completed


def _failure_detail(*streams: str | None) -> str:
    """wrangler's ``[ERROR]`` line and the detail beneath it, colour stripped; never its log trailer."""
    for stream in streams:
        lines = [
            stripped for line in (stream or "").splitlines()
            if (stripped := _ANSI.sub("", line).strip()) and _LOG_TRAILER not in stripped
        ]
        if not lines:
            continue
        for index, line in enumerate(lines):
            if _ERROR_MARK in line:
                detail = lines[index + 1 : index + 2]
                if detail and not detail[0].startswith(_ISSUE_NUDGE):
                    return f"{line.lstrip('✘ ')} {detail[0]}"
                return line.lstrip("✘ ")
        return lines[-1]
    return "no output"


def _deployment_of(stdout: str) -> Deployment:
    """The URLs wrangler printed; exit 0 without them is an unconfirmed deploy, not a success."""
    url = _DEPLOYMENT_URL.search(stdout)
    if url is None:
        raise UploadError(
            "wrangler exited 0 but printed no deployment URL — the deploy's final status could not be "
            "ascertained; check the project's deployments in the Cloudflare dashboard"
        )
    alias = _ALIAS_URL.search(stdout)
    return Deployment(url=url.group(1), alias=alias.group(1) if alias else None)


__all__ = ["DEFAULT_WRANGLER", "Deployment", "Runner", "UploadError", "deploy"]
