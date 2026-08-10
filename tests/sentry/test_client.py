# ABOUTME: Tests for the Sentry REST connector — request shape, error mapping, and the env factory.
# ABOUTME: The HTTP opener is injected, so nothing here reaches sentry.io and no token is required.

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from oversteward.sentry.client import (
    TOKEN_ENV,
    SentryClient,
    SentryConfigError,
    SentryUnavailableError,
    client_from_env,
    resolve_token,
)

from .fakes import AG, GS, TOKEN

ISSUE_ID = "42"
NO_DOTENV = Path("/nonexistent/.env")
UNAUTHORIZED = urllib.error.HTTPError("https://sentry.io", 401, "Unauthorized", {}, None)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _Opener:
    """Records every request and replays one queued body per call."""

    def __init__(self, *bodies) -> None:
        self.bodies = list(bodies)
        self.requests: list = []
        self.timeout: float | None = None

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeout = timeout
        body = self.bodies.pop(0) if self.bodies else b"[]"
        return _Response(body if isinstance(body, bytes) else json.dumps(body).encode())


def _client(opener) -> SentryClient:
    return SentryClient(TOKEN, org="the-almoner-llc", opener=opener)


def _raising(exc):
    def opener(_request, timeout=None):
        raise exc

    return opener


# --- reads ------------------------------------------------------------------


def test_list_projects_enumerates_the_org_rather_than_assuming_slugs() -> None:
    opener = _Opener([{"slug": AG, "name": "AG"}, {"slug": GS, "name": "GS"}])

    projects = _client(opener).list_projects()

    assert [p.slug for p in projects] == [AG, GS]
    assert opener.requests[0].full_url.endswith("/organizations/the-almoner-llc/projects/")


def test_list_unresolved_issues_asks_only_for_unresolved() -> None:
    opener = _Opener([])

    _client(opener).list_unresolved_issues(AG)

    assert "query=is%3Aunresolved" in opener.requests[0].full_url
    assert f"/projects/the-almoner-llc/{AG}/issues/" in opener.requests[0].full_url


def test_an_issue_carries_the_project_it_was_fetched_from() -> None:
    row = {"id": ISSUE_ID, "shortId": "PYTHON-9", "title": "boom", "firstSeen": "2026-08-01T00:00:00Z"}

    issues = _client(_Opener([row])).list_unresolved_issues(GS)

    assert issues[0].project == GS
    assert issues[0].short_id == "PYTHON-9"
    assert issues[0].id == ISSUE_ID


def test_every_request_carries_bearer_auth_and_a_timeout() -> None:
    opener = _Opener([])

    _client(opener).list_projects()

    assert opener.requests[0].get_header("Authorization") == f"Bearer {TOKEN}"
    assert opener.timeout > 0


# --- writes -----------------------------------------------------------------


def test_resolve_issue_sets_status_resolved_never_ignored() -> None:
    opener = _Opener(b"{}")

    _client(opener).resolve_issue(ISSUE_ID)

    assert opener.requests[0].method == "PUT"
    assert json.loads(opener.requests[0].data) == {"status": "resolved"}


def test_a_reason_is_posted_as_a_comment_before_the_resolve() -> None:
    opener = _Opener(b"{}", b"{}")

    _client(opener).resolve_issue(ISSUE_ID, comment="noise from a retired cron")

    assert opener.requests[0].full_url.endswith(f"/issues/{ISSUE_ID}/comments/")
    assert json.loads(opener.requests[0].data)["text"] == "noise from a retired cron"
    assert opener.requests[1].method == "PUT"


# --- failure surfaces -------------------------------------------------------


def test_an_auth_failure_surfaces_as_unavailable_with_its_status_code() -> None:
    with pytest.raises(SentryUnavailableError, match="HTTP 401"):
        _client(_raising(UNAUTHORIZED)).list_projects()


def test_an_unreachable_host_surfaces_as_unavailable() -> None:
    with pytest.raises(SentryUnavailableError, match="unreachable"):
        _client(_raising(urllib.error.URLError("no route to host"))).list_projects()


def test_unparseable_json_is_reported_rather_than_read_as_empty() -> None:
    with pytest.raises(SentryUnavailableError, match="unparseable"):
        _client(_Opener(b"<html>502</html>")).list_projects()


def test_a_failure_message_never_carries_the_token() -> None:
    with pytest.raises(SentryUnavailableError) as caught:
        _client(_raising(UNAUTHORIZED)).list_projects()

    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__, "the upstream error must not render in the traceback"


# --- the factory (the only place that reads the environment) ----------------


def test_the_factory_uses_an_exported_token() -> None:
    assert isinstance(client_from_env({TOKEN_ENV: TOKEN}, NO_DOTENV), SentryClient)


def test_resolve_token_refuses_when_no_token_is_configured() -> None:
    with pytest.raises(SentryConfigError, match=TOKEN_ENV):
        resolve_token({}, NO_DOTENV)


def test_resolve_token_falls_back_to_a_dotenv_file(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{TOKEN_ENV}={TOKEN}\n")

    assert resolve_token({}, dotenv) == TOKEN


def test_an_exported_token_wins_over_the_dotenv_file(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{TOKEN_ENV}=from-file\n")

    assert resolve_token({TOKEN_ENV: TOKEN}, dotenv) == TOKEN


def test_a_blank_token_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match=TOKEN_ENV):
        SentryClient("")
