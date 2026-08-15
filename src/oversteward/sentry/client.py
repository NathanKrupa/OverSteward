# ABOUTME: INNER connector for the Sentry REST API — lists unresolved issues and resolves them.
# ABOUTME: Token is injected via __init__; only client_from_env() reads the environment (ARCH-020).

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .models import SentryIssue, SentryProject

# Repo root: src/oversteward/sentry/client.py -> up three parents.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOTENV_PATH = _REPO_ROOT / ".env"

TOKEN_ENV = "SENTRY_API_TOKEN"
DEFAULT_ORG = "the-almoner-llc"
DEFAULT_BASE_URL = "https://sentry.io/api/0"
DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 100
UNRESOLVED_QUERY = "is:unresolved"
RESOLVED_STATUS = "resolved"


class SentryConfigError(RuntimeError):
    """Raised when the Sentry API token is not configured."""


class SentryUnavailableError(RuntimeError):
    """Raised when Sentry could not be read or written.

    Deliberately distinct from "there was nothing to report": a sweep that could
    not look must never render like a sweep that looked and found nothing.
    """


class SentryClient:
    """Talks to exactly one external system: the Sentry REST API.

    No decisions live here — it fetches, parses, and writes status. What counts
    as triaged, and what to do about an issue, belong to the triage service.
    """

    def __init__(
        self,
        token: str,
        *,
        org: str = DEFAULT_ORG,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Callable | None = None,
    ) -> None:
        if not token:
            raise ValueError(f"{TOKEN_ENV} must not be empty — build the client via client_from_env().")
        self._token = token
        self.org = org
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = opener if opener is not None else urllib.request.urlopen

    def list_projects(self) -> list[SentryProject]:
        """Every project in the organization, enumerated rather than hardcoded."""
        payload = self._request(f"/organizations/{urllib.parse.quote(self.org)}/projects/")
        return [_project_from_api(row) for row in payload if row.get("slug")]

    def list_unresolved_issues(
        self,
        project_slug: str,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[SentryIssue]:
        """Unresolved issues for one project, bounded by ``limit``."""
        query = urllib.parse.urlencode({"query": UNRESOLVED_QUERY, "limit": limit})
        path = (
            f"/projects/{urllib.parse.quote(self.org)}"
            f"/{urllib.parse.quote(project_slug)}/issues/?{query}"
        )
        payload = self._request(path)
        return [_issue_from_api(row, project_slug) for row in payload]

    def resolve_issue(self, issue_id: str, *, comment: str = "") -> None:
        """Mark an issue resolved — never ignored, so a regression reopens loudly."""
        if comment:
            self._request(
                f"/issues/{urllib.parse.quote(issue_id)}/comments/",
                method="POST",
                payload={"text": comment},
            )
        self._request(
            f"/issues/{urllib.parse.quote(issue_id)}/",
            method="PUT",
            payload={"status": RESOLVED_STATUS},
        )

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None):
        """One HTTP round-trip. Failures surface as SentryUnavailableError, never as a token.

        The exception chain is deliberately suppressed (``from None``): a
        dispatch transcript renders tracebacks, and the underlying ``HTTPError``
        carries the response object — headers and body included — while adding
        nothing the connector's own message does not already say.
        """
        request = urllib.request.Request(  # noqa: SEC-006 — base_url is injected config, not user input
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
        )
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise SentryUnavailableError(f"Sentry returned HTTP {exc.code} for {method} {path}") from None
        except urllib.error.URLError as exc:
            raise SentryUnavailableError(f"Sentry unreachable {_where(method, path)}{exc.reason}") from None
        except OSError as exc:
            raise SentryUnavailableError(f"Sentry read failed {_where(method, path)}{exc}") from None
        return _decode(body, method, path)


def _where(method: str, path: str) -> str:
    """The call site, as a message prefix. Never carries credentials."""
    return f"({method} {path}): "


def _decode(body: bytes, method: str, path: str):
    """Parse a Sentry response body, or say plainly that it was unreadable."""
    if not body:
        return []
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SentryUnavailableError(f"Sentry sent unparseable JSON {_where(method, path)}{exc}") from None


def _project_from_api(payload: dict) -> SentryProject:
    """Wire format is the connector's business; the model stays a plain value."""
    slug = str(payload.get("slug", ""))
    return SentryProject(slug=slug, name=str(payload.get("name") or slug))


def _issue_from_api(payload: dict, project_slug: str) -> SentryIssue:
    return SentryIssue(
        id=str(payload.get("id", "")),
        short_id=str(payload.get("shortId", "")),
        project=project_slug,
        title=str(payload.get("title", "")),
        first_seen=str(payload.get("firstSeen") or ""),
        permalink=str(payload.get("permalink") or ""),
        count=int(payload.get("count") or 0),
    )


def resolve_token(
    env: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> str:
    """Read the Sentry API token from the environment (ARCH-020).

    This is the only place that touches ``os.environ``. If the token is not
    already exported, fall back to the OverSteward repo-root ``.env``, parsed
    in-process — never shell-sourced (credential-hygiene.md). An exported value
    wins over ``.env``, matching ``load_dotenv``'s ``override=False`` default.
    """
    source = env if env is not None else os.environ
    token = source.get(TOKEN_ENV) or _token_from_dotenv(dotenv_path)
    if not token:
        raise SentryConfigError(
            f"{TOKEN_ENV} is not set — the Sentry triage sweep needs an API token with "
            "org:read, project:read and event:write scopes. Export it or add it to the "
            "OverSteward repo-root .env."
        )
    return token


def client_from_env(
    env: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
    *,
    org: str = DEFAULT_ORG,
) -> SentryClient:
    """Factory: build a client around the configured token."""
    return SentryClient(resolve_token(env, dotenv_path), org=org)


def _token_from_dotenv(dotenv_path: Path | None) -> str | None:
    """Return the token from a ``.env`` file, or None if unavailable.

    ``dotenv_values`` parses without mutating the process environment; the
    exported-wins ordering is enforced by the caller.
    """
    path = dotenv_path if dotenv_path is not None else _DEFAULT_DOTENV_PATH
    if not path.is_file():
        return None
    from dotenv import dotenv_values  # noqa: PLC0415 — optional dep, imported lazily

    return dotenv_values(path).get(TOKEN_ENV) or None
