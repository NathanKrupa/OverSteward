# ABOUTME: Tests for the AG ops connector — request shape, the three-way error split, the env factory.
# ABOUTME: The HTTP opener is injected, so nothing here reaches aigranthelper and no token is needed.

from __future__ import annotations

import email.message
import io
import json
import urllib.error
from pathlib import Path

import pytest

from oversteward.ag_ops.client import (
    BASE_URL_ENV,
    DEFAULT_BASE_URL,
    REPORTS_TOKEN_ENV,
    USER_AGENT,
    VERDICTS_TOKEN_ENV,
    AgOpsClient,
    AgOpsConfigError,
    AgOpsNotFoundError,
    AgOpsUnavailableError,
    client_from_env,
)

from .fakes import BASE_URL, UNCONFIGURED_MESSAGE, manifest

READ_TOKEN = "ops-reports-not-a-real-token"
WRITE_TOKEN = "ops-verdicts-not-a-real-token"
NO_DOTENV = Path("/nonexistent/.env")
MANIFEST_URL = f"{BASE_URL}/internal/ops/reports/"


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
        body = self.bodies.pop(0) if self.bodies else {}
        return _Response(body if isinstance(body, bytes) else json.dumps(body).encode())


class _Failing:
    """An opener that always raises the exception it was built with."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.requests: list = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        raise self._error


def _http_error(code: int, body: dict | bytes, content_type: str = "application/json") -> urllib.error.HTTPError:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = email.message.Message()
    headers["Content-Type"] = content_type
    return urllib.error.HTTPError(MANIFEST_URL, code, "err", headers, io.BytesIO(payload))


def _cloudflare_block(code: int = 403) -> urllib.error.HTTPError:
    """What the CDN actually answered a default-User-Agent request with (OS#394)."""
    return _http_error(code, b"error code: 1010", content_type="text/plain; charset=UTF-8")


def _client(opener, *, reports_token: str = READ_TOKEN, verdicts_token: str = WRITE_TOKEN) -> AgOpsClient:
    return AgOpsClient(
        reports_token=reports_token,
        verdicts_token=verdicts_token,
        base_url=BASE_URL,
        opener=opener,
    )


# --- request shape ----------------------------------------------------------


def test_manifest_gets_the_published_path_with_the_read_token() -> None:
    opener = _Opener(manifest())
    payload = _client(opener).manifest()

    request = opener.requests[0]
    assert request.full_url == MANIFEST_URL
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == f"Bearer {READ_TOKEN}"
    assert payload["contract_version"] == 1


def test_report_carries_the_cursor_and_page_size_as_query_params() -> None:
    opener = _Opener({"report": "feedback_queue"})
    _client(opener).report("feedback_queue", since="2026-08-01T00:00:00Z", limit=25)

    url = opener.requests[0].full_url
    assert url.startswith(f"{BASE_URL}/internal/ops/reports/feedback_queue/?")
    assert "since=2026-08-01T00%3A00%3A00Z" in url
    assert "limit=25" in url


def test_report_without_a_cursor_sends_no_query_string() -> None:
    opener = _Opener({"report": "feedback_queue"})
    _client(opener).report("feedback_queue")

    assert opener.requests[0].full_url == f"{BASE_URL}/internal/ops/reports/feedback_queue/"


def test_post_verdicts_uses_the_write_token_and_the_batch_envelope() -> None:
    opener = _Opener({"recorded": 1})
    items = [{"kind": "feedback", "id": "abc", "status": "responded"}]
    _client(opener).post_verdicts(items)

    request = opener.requests[0]
    assert request.full_url == f"{BASE_URL}/internal/ops/verdicts/"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {WRITE_TOKEN}"
    assert json.loads(request.data) == {"verdicts": items}


# --- the User-Agent the edge lets through (OS#394) ---------------------------


def test_every_request_announces_this_tools_user_agent() -> None:
    """urllib's default UA is blocked by Cloudflare before the producer sees it."""
    opener = _Opener(manifest(), {"report": "feedback_queue"}, {"recorded": 0})
    client = _client(opener)
    client.manifest()
    client.report("feedback_queue")
    client.post_verdicts([])

    sent = [request.get_header("User-agent") for request in opener.requests]
    assert sent == [USER_AGENT] * 3


def test_the_user_agent_names_the_tool_and_its_version() -> None:
    assert USER_AGENT.startswith("oversteward-ag-ops-triage/")
    assert "urllib" not in USER_AGENT


# --- the three-way error split ----------------------------------------------


def test_a_missing_read_token_is_a_config_error_naming_the_setting() -> None:
    with pytest.raises(AgOpsConfigError, match=REPORTS_TOKEN_ENV):
        _client(_Opener(), reports_token="").manifest()


def test_a_missing_write_token_is_a_config_error_naming_the_setting() -> None:
    with pytest.raises(AgOpsConfigError, match=VERDICTS_TOKEN_ENV):
        _client(_Opener(), verdicts_token="").post_verdicts([])


def test_a_sweep_never_needs_the_write_token() -> None:
    opener = _Opener(manifest())

    assert _client(opener, verdicts_token="").manifest()["contract_version"] == 1


def test_the_producers_unconfigured_503_is_a_config_error_not_an_outage() -> None:
    opener = _Failing(_http_error(503, {"error": UNCONFIGURED_MESSAGE}))

    with pytest.raises(AgOpsConfigError, match=UNCONFIGURED_MESSAGE):
        _client(opener).manifest()


def test_a_problem_details_503_is_an_outage_not_a_config_error() -> None:
    problem = {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "feedback.Feedback could not be read",
        "source": "feedback.Feedback",
    }
    opener = _Failing(_http_error(503, problem))

    with pytest.raises(AgOpsUnavailableError, match="feedback.Feedback could not be read") as caught:
        _client(opener).manifest()
    assert not isinstance(caught.value, AgOpsConfigError)


def test_an_undiagnosed_503_carrying_the_json_envelope_reads_as_an_outage() -> None:
    """A producer-shaped body with neither diagnosis key is still the producer answering."""
    opener = _Failing(_http_error(503, {}))

    with pytest.raises(AgOpsUnavailableError, match="no diagnosis"):
        _client(opener).manifest()


def test_a_rejected_credential_is_a_config_error() -> None:
    opener = _Failing(_http_error(401, {"error": "valid bearer token required"}))

    with pytest.raises(AgOpsConfigError, match="401"):
        _client(opener).manifest()


# --- edge interference is never a credential verdict (OS#394) ----------------


def test_a_cloudflare_403_is_could_not_look_never_a_credential_verdict() -> None:
    """The measured production failure: text/plain 'error code: 1010' from the CDN."""
    opener = _Failing(_cloudflare_block())

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).manifest()
    message = str(caught.value)
    assert not isinstance(caught.value, AgOpsConfigError)
    assert "edge" in message
    assert "403" in message
    assert "text/plain" in message
    assert "token" not in message


def test_a_non_json_401_is_edge_interference_not_a_rejected_credential() -> None:
    opener = _Failing(_http_error(401, b"<html>Attention Required!</html>", content_type="text/html"))

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).manifest()
    assert not isinstance(caught.value, AgOpsConfigError)
    assert "no credential was checked" in str(caught.value)


def test_a_non_json_503_is_edge_interference_not_an_unconfigured_producer() -> None:
    opener = _Failing(_http_error(503, b"<html>origin down</html>", content_type="text/html"))

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).manifest()
    assert not isinstance(caught.value, AgOpsConfigError)
    assert "edge" in str(caught.value)


def test_a_json_array_body_is_not_the_producers_envelope() -> None:
    opener = _Failing(_http_error(403, b"[]"))

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).manifest()
    assert not isinstance(caught.value, AgOpsConfigError)


def test_a_json_403_from_the_producer_is_still_a_credential_verdict() -> None:
    """The correction must not over-reach: a real producer refusal still names the token."""
    opener = _Failing(_http_error(403, {"error": "valid bearer token required"}))

    with pytest.raises(AgOpsConfigError, match="token in .env"):
        _client(opener).manifest()


def test_an_html_404_is_still_not_found_so_a_pre_promote_sweep_says_not_mounted() -> None:
    """Django's own 404 page is HTML (measured against production, OS#394).

    404 is deliberately exempt from the JSON-envelope requirement: it asserts
    nothing about our credential, so requiring the envelope here would turn an
    honest "surface not mounted" into a false edge report.
    """
    opener = _Failing(_http_error(404, b"<!DOCTYPE html><html>Page not found</html>", content_type="text/html"))

    with pytest.raises(AgOpsNotFoundError):
        _client(opener).manifest()


def test_no_edge_message_ever_carries_a_token() -> None:
    opener = _Failing(_cloudflare_block())

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).manifest()
    assert READ_TOKEN not in str(caught.value)


def test_a_throttled_caller_could_not_look() -> None:
    opener = _Failing(_http_error(429, {"error": "too many failed authentication attempts"}))

    with pytest.raises(AgOpsUnavailableError, match="429"):
        _client(opener).manifest()


def test_a_404_is_its_own_error_so_the_service_can_judge_it() -> None:
    opener = _Failing(_http_error(404, {"detail": "no report named 'nope'"}))

    with pytest.raises(AgOpsNotFoundError):
        _client(opener).report("nope")


def test_an_unreachable_host_could_not_look() -> None:
    opener = _Failing(urllib.error.URLError("connection refused"))

    with pytest.raises(AgOpsUnavailableError, match="unreachable"):
        _client(opener).manifest()


def test_a_timeout_could_not_look() -> None:
    opener = _Failing(TimeoutError("timed out"))

    with pytest.raises(AgOpsUnavailableError, match="read failed"):
        _client(opener).manifest()


def test_an_unparseable_body_could_not_look() -> None:
    with pytest.raises(AgOpsUnavailableError, match="unparseable JSON"):
        _client(_Opener(b"not json")).manifest()


def test_a_non_object_body_could_not_look() -> None:
    with pytest.raises(AgOpsUnavailableError, match="non-object body"):
        _client(_Opener(b"[1, 2]")).manifest()


def test_no_failure_message_ever_carries_a_token() -> None:
    opener = _Failing(_http_error(401, {"error": "valid bearer token required"}))

    with pytest.raises(AgOpsConfigError) as caught:
        _client(opener).manifest()
    assert READ_TOKEN not in str(caught.value)
    assert WRITE_TOKEN not in str(caught.value)


# --- the environment factory (ARCH-020) -------------------------------------


def test_the_factory_reads_both_tokens_and_the_base_url() -> None:
    env = {
        REPORTS_TOKEN_ENV: READ_TOKEN,
        VERDICTS_TOKEN_ENV: WRITE_TOKEN,
        BASE_URL_ENV: "https://staging.example/",
    }
    client = client_from_env(env, NO_DOTENV, opener=_Opener(manifest()))

    assert client.base_url == "https://staging.example"
    assert client.manifest()["contract_version"] == 1


def test_the_factory_defaults_to_production_when_no_base_url_is_set() -> None:
    client = client_from_env({REPORTS_TOKEN_ENV: READ_TOKEN}, NO_DOTENV)

    assert client.base_url == DEFAULT_BASE_URL


def test_the_factory_builds_a_client_even_with_no_tokens_at_all() -> None:
    """Absent tokens are the method's business — a sweep must not fail over the write token."""
    client = client_from_env({}, NO_DOTENV, opener=_Opener())

    with pytest.raises(AgOpsConfigError, match=REPORTS_TOKEN_ENV):
        client.manifest()


def test_the_factory_falls_back_to_the_repo_dotenv_parsed_in_process(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{REPORTS_TOKEN_ENV}={READ_TOKEN}\n{BASE_URL_ENV}=https://dotenv.example\n")
    client = client_from_env({}, dotenv, opener=_Opener(manifest()))

    assert client.base_url == "https://dotenv.example"
    assert client.manifest()["contract_version"] == 1


def test_an_exported_value_wins_over_the_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{BASE_URL_ENV}=https://dotenv.example\n")
    client = client_from_env({BASE_URL_ENV: "https://exported.example"}, dotenv)

    assert client.base_url == "https://exported.example"
