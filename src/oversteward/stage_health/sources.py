# ABOUTME: INNER transports for /stage-health — `dq health --json` locally or over `railway ssh`; GitHub state.
# ABOUTME: No decisions: each runs one external system and maps its failures onto named exceptions.

"""The two external systems the stage-health sweep reads.

:class:`GrantspiderHealthCli` runs ``grantspider dq health --json`` from the
GrantSpider primary checkout named in ``registry.yaml`` — the checkout that
tracks what production runs. The command is a read-only production read. It
must run with that checkout as its working directory: the thresholds file it
reads is a relative path, and its settings load that checkout's own ``.env``.
Its stderr is captured and never echoed, because a traceback from a database
driver is where a connection string would leak (credential-hygiene.md).

:class:`RailwayHealthSsh` runs the same command inside the production
GrantSpider service through ``railway ssh`` (OS#540), for a laptop whose route
to Neon is black-holed. The Railway CLI wraps the command's output in its own
notices, so the transport keeps only the document's span of stdout — from the
first line opening with ``{`` to the last closing with ``}`` — and treats a
stdout with no such span as the route having failed. Its stderr carries the
remote's stderr too, so it is withheld for the same reason.

:class:`GithubIssueStates` answers whether an issue a verdict points at is still
open, through the estate's existing ``gh`` transport. The two classes share a
module, not a connection: each talks to exactly one system.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oversteward.board.client import GhError, NotFoundError, gh_json

#: The registry context whose checkout holds the producer.
GRANTSPIDER_CONTEXT_ID = "grantspider"
#: The producer, relative to that checkout.
PRODUCER_BINARY = Path(".venv") / "bin" / "grantspider"
PRODUCER_COMMAND = ("dq", "health", "--json")
#: Generous: the producer reads one Neon table, but a cold Neon compute takes a while to wake.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: ``railway ssh`` from the Railway-linked GrantSpider checkout, into the production service.
RAILWAY_BINARY = "railway"
RAILWAY_SERVICE = "grantspider"
RAILWAY_ENVIRONMENT = "production"
#: The producer as the production service's PATH names it.
REMOTE_PRODUCER = "grantspider"
DEFAULT_REMOTE_TIMEOUT_SECONDS = 120.0

#: What :class:`GithubIssueStates` returns for an issue GitHub answers 404 for.
STATE_MISSING = "missing"


class ProducerConfigError(RuntimeError):
    """Nothing is configured to look at: the registry names no GrantSpider checkout."""


class ProducerUnavailableError(RuntimeError):
    """The producer could not be run at all — a missing binary, or a timeout."""


class ProducerTimeoutError(ProducerUnavailableError):
    """The producer started and did not finish within its timeout."""


class IssueStateUnavailableError(RuntimeError):
    """GitHub could not be read for an issue's state."""


@dataclass(frozen=True)
class ProducerRun:
    """What the producer process left behind: its exit code and its stdout."""

    returncode: int
    stdout: str


def checkout_from_registry(registry: dict[str, Any]) -> Path:
    """The GrantSpider checkout ``registry.yaml`` declares. Takes loaded data, never a path."""
    for context in registry.get("contexts") or []:
        if context.get("id") == GRANTSPIDER_CONTEXT_ID and context.get("local_path"):
            return Path(context["local_path"])
    raise ProducerConfigError(
        f"registry.yaml has no {GRANTSPIDER_CONTEXT_ID!r} context with a local_path"
    )


class GrantspiderHealthCli:
    """Runs ``grantspider dq health --json`` in the GrantSpider checkout."""

    def __init__(
        self,
        checkout: Path,
        *,
        days: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._checkout = checkout
        self._days = days
        self._timeout = timeout
        self._run = run

    def argv(self) -> list[str]:
        argv = [str(self._checkout / PRODUCER_BINARY), *PRODUCER_COMMAND]
        if self._days is not None:
            argv += ["--days", str(self._days)]
        return argv

    def run(self) -> ProducerRun:
        try:
            proc = self._run(
                self.argv(),
                cwd=self._checkout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProducerTimeoutError(
                f"{self._checkout / PRODUCER_BINARY} timed out after {self._timeout:.0f}s"
            ) from exc
        except OSError as exc:
            raise ProducerUnavailableError(
                f"could not run {self._checkout / PRODUCER_BINARY}: {type(exc).__name__}"
            ) from exc
        return ProducerRun(returncode=proc.returncode, stdout=proc.stdout or "")


def document_span(stdout: str) -> str:
    """The lines from the first opening with ``{`` to the last closing with ``}``, else ``""``."""
    lines = stdout.splitlines()
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith("{")]
    ends = [i for i, line in enumerate(lines) if line.rstrip().endswith("}")]
    if not starts or not ends or ends[-1] < starts[0]:
        return ""
    return "\n".join(lines[starts[0] : ends[-1] + 1])


class RailwayHealthSsh:
    """Runs ``grantspider dq health --json`` inside the production service via ``railway ssh``."""

    def __init__(
        self,
        checkout: Path,
        *,
        days: int | None = None,
        timeout: float = DEFAULT_REMOTE_TIMEOUT_SECONDS,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._checkout = checkout
        self._days = days
        self._timeout = timeout
        self._run = run

    def argv(self) -> list[str]:
        argv = [
            RAILWAY_BINARY, "ssh", "--service", RAILWAY_SERVICE,
            "--environment", RAILWAY_ENVIRONMENT, "--", REMOTE_PRODUCER, *PRODUCER_COMMAND,
        ]
        if self._days is not None:
            argv += ["--days", str(self._days)]
        return argv

    def run(self) -> ProducerRun:
        try:
            proc = self._run(
                self.argv(),
                cwd=self._checkout,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ProducerUnavailableError("railway CLI not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProducerUnavailableError(
                f"railway ssh timed out after {self._timeout:.0f}s"
            ) from exc
        except OSError as exc:
            raise ProducerUnavailableError(f"could not run railway ssh: {type(exc).__name__}") from exc
        document = document_span(proc.stdout or "")
        if not document:
            raise ProducerUnavailableError(
                f"railway ssh exited {proc.returncode} with no health document on stdout "
                "(its stderr is withheld: it carries the remote's)"
            )
        return ProducerRun(returncode=proc.returncode, stdout=document)


class GithubIssueStates:
    """``(repo, number) -> "open" | "closed" | "missing"`` through ``gh api``."""

    def __init__(self, *, run: Callable[[list[str]], Any] = gh_json) -> None:
        self._run = run

    def __call__(self, repo: str, number: int) -> str:
        try:
            payload = self._run(["api", f"repos/{repo}/issues/{number}"])
        except NotFoundError:
            return STATE_MISSING
        except (GhError, ValueError) as exc:
            raise IssueStateUnavailableError(f"{repo}#{number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise IssueStateUnavailableError(f"{repo}#{number}: gh returned no issue object")
        return str(payload.get("state", ""))


__all__ = [
    "GRANTSPIDER_CONTEXT_ID",
    "STATE_MISSING",
    "GithubIssueStates",
    "GrantspiderHealthCli",
    "IssueStateUnavailableError",
    "ProducerConfigError",
    "ProducerRun",
    "ProducerTimeoutError",
    "ProducerUnavailableError",
    "RailwayHealthSsh",
    "checkout_from_registry",
    "document_span",
]
