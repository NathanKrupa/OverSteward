# ABOUTME: Tests for the AG ops connector — request shape, the three-way error split, the env factory.
# ABOUTME: The HTTP opener is injected, so nothing here reaches aigranthelper and no token is needed.

from __future__ import annotations

import email.message
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
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
    _RedirectPolicy,
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


def test_the_default_base_url_is_the_apex_that_answers_without_a_redirect() -> None:
    """``www`` answers every path with a 301 to the apex, which turns a POST into a GET (OS#633)."""
    assert urllib.parse.urlsplit(DEFAULT_BASE_URL).hostname == "aigranthelper.com"


# --- a write is never re-sent to a redirect (OS#633) --------------------------
#
# These run the client's *default* opener against a real HTTP server on the
# loopback, because the defect lives in that opener: urllib follows a 301 or
# 302 on a POST by re-issuing a bodiless GET, and the producer answers the GET
# with a 405 that used to be reported as the edge.

_REDIRECT_TARGET = "/apex/internal/ops/verdicts/"
_LOOP_PATH = "/internal/ops/reports/loop/"


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Answers a POST with ``redirect_status`` to the apex path; answers every GET with 405 HTML."""

    seen: list[tuple[str, str]] = []
    redirect_status = 301

    def do_POST(self) -> None:  # noqa: N802 — the stdlib's handler naming
        type(self).seen.append(("POST", self.path))
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(type(self).redirect_status)
        self.send_header("Location", f"http://{self.headers['Host']}{_REDIRECT_TARGET}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 — the stdlib's handler naming
        type(self).seen.append(("GET", self.path))
        if self.path == "/internal/ops/reports/":
            self.send_response(301)
            self.send_header("Location", f"http://{self.headers['Host']}/apex/internal/ops/reports/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == _LOOP_PATH:
            self.send_response(302)
            self.send_header("Location", f"http://{self.headers['Host']}{_LOOP_PATH}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/apex/internal/ops/reports/":
            self._send(200, json.dumps(manifest()).encode(), "application/json")
            return
        self._send(405, b"<html>Method Not Allowed</html>", "text/html")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        """Keep the test output pristine."""


@pytest.fixture
def redirecting_server():
    """A loopback server whose handler class records every request it answered."""
    handler = type("Handler", (_Recorder,), {"seen": []})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _default_opener_client(server) -> AgOpsClient:
    host, port = server.server_address[:2]
    return AgOpsClient(reports_token=READ_TOKEN, verdicts_token=WRITE_TOKEN, base_url=f"http://{host}:{port}")


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirected_write_is_refused_naming_the_location_and_the_setting(redirecting_server, status) -> None:
    server, handler = redirecting_server
    handler.redirect_status = status

    with pytest.raises(AgOpsUnavailableError) as caught:
        _default_opener_client(server).post_verdicts([{"kind": "feedback", "id": "abc", "status": "responded"}])

    assert handler.seen == [("POST", "/internal/ops/verdicts/")], "a follow-up request was issued"
    message = str(caught.value)
    host, port = server.server_address[:2]
    assert f"redirected to http://{host}:{port}{_REDIRECT_TARGET}" in message
    assert BASE_URL_ENV in message
    assert f"HTTP {status}" in message
    assert "a write is never re-sent to a redirect" in message
    assert "edge" not in message
    assert WRITE_TOKEN not in message


def test_a_redirected_read_still_follows_to_the_answer(redirecting_server) -> None:
    """Only writes refuse: a GET survives a redirect intact, so a sweep keeps working."""
    server, handler = redirecting_server

    assert _default_opener_client(server).manifest()["contract_version"] == 1
    assert handler.seen == [("GET", "/internal/ops/reports/"), ("GET", "/apex/internal/ops/reports/")]


def test_a_read_caught_in_a_redirect_loop_is_not_reported_as_a_refused_write(redirecting_server) -> None:
    """urllib gives up on a looping GET with the 3xx itself; that is no write refusal."""
    server, _handler = redirecting_server

    with pytest.raises(AgOpsUnavailableError) as caught:
        _default_opener_client(server).report("loop")

    message = str(caught.value)
    assert "HTTP 302" in message
    assert "(GET /internal/ops/reports/loop/)" in message
    assert BASE_URL_ENV in message
    assert "write" not in message
    assert READ_TOKEN not in message


def test_a_non_json_405_is_not_blamed_on_the_edge() -> None:
    """Only 401/403/503 make a claim the producer's envelope must back; a 405 makes none (OS#633)."""
    opener = _Failing(_http_error(405, b"<html>Method Not Allowed</html>", content_type="text/html"))

    with pytest.raises(AgOpsUnavailableError) as caught:
        _client(opener).post_verdicts([])
    message = str(caught.value)
    assert not isinstance(caught.value, AgOpsConfigError)
    assert "405" in message
    assert "text/html" in message
    assert "edge" not in message


# --- a read is never followed to another origin (OS#719) ----------------------
#
# urllib copies every header but the content ones onto a followed request, so
# following a GET to another origin hands it ``Authorization: Bearer <token>``.
# Two loopback servers on different ports are two origins: the first redirects,
# the second records whatever reaches it, the bearer header included.

_VIA_PREFIX = "/via"


class _OffsiteRedirector(http.server.BaseHTTPRequestHandler):
    """Answers every GET with ``redirect_status`` to the same path on ``offsite``.

    With ``via_same_origin`` set, the first hop is a 301 to ``/via<path>`` on
    this server, so the cross-origin hop is the second one in the chain.
    """

    seen: list[tuple[str, str]] = []
    redirect_status = 302
    offsite = ""
    via_same_origin = False

    def do_GET(self) -> None:  # noqa: N802 — the stdlib's handler naming
        type(self).seen.append(("GET", self.path))
        if type(self).via_same_origin and not self.path.startswith(_VIA_PREFIX):
            self._redirect(301, f"http://{self.headers['Host']}{_VIA_PREFIX}{self.path}")
            return
        path = self.path.removeprefix(_VIA_PREFIX)
        self._redirect(type(self).redirect_status, f"{type(self).offsite}{path}")

    def _redirect(self, status: int, location: str) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args) -> None:
        """Keep the test output pristine."""


class _Offsite(http.server.BaseHTTPRequestHandler):
    """Another origin: records each request with the bearer header it carried, answers a manifest."""

    seen: list[tuple[str, str, str]] = []

    def do_GET(self) -> None:  # noqa: N802 — the stdlib's handler naming
        type(self).seen.append(("GET", self.path, self.headers.get("Authorization", "")))
        body = json.dumps(manifest(entries=[])).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        """Keep the test output pristine."""


def _origin_of(server) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


@pytest.fixture
def two_origins():
    """A redirecting server and an offsite one on another port; yields both handler classes."""
    offsite_handler = type("Offsite", (_Offsite,), {"seen": []})
    offsite = http.server.ThreadingHTTPServer(("127.0.0.1", 0), offsite_handler)
    origin_handler = type(
        "Origin", (_OffsiteRedirector,), {"seen": [], "offsite": _origin_of(offsite)}
    )
    origin = http.server.ThreadingHTTPServer(("127.0.0.1", 0), origin_handler)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (offsite, origin)]
    for thread in threads:
        thread.start()
    try:
        yield origin, origin_handler, offsite, offsite_handler
    finally:
        for server in (origin, offsite):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_read_redirected_to_another_origin_is_refused_and_the_token_never_leaves(two_origins, status) -> None:
    origin, origin_handler, offsite, offsite_handler = two_origins
    origin_handler.redirect_status = status

    with pytest.raises(AgOpsUnavailableError) as caught:
        _default_opener_client(origin).manifest()

    assert offsite_handler.seen == [], "the bearer token was carried to another origin"
    assert origin_handler.seen == [("GET", "/internal/ops/reports/")]
    message = str(caught.value)
    assert f"HTTP {status}" in message
    assert f"redirected to {_origin_of(offsite)}/internal/ops/reports/" in message
    assert BASE_URL_ENV in message
    assert "a read is never followed to another origin" in message
    assert "loop" not in message
    assert "write" not in message
    assert READ_TOKEN not in message


def test_a_same_origin_hop_is_followed_and_the_cross_origin_hop_after_it_refused(two_origins) -> None:
    origin, origin_handler, _offsite, offsite_handler = two_origins
    origin_handler.via_same_origin = True

    with pytest.raises(AgOpsUnavailableError) as caught:
        _default_opener_client(origin).manifest()

    assert offsite_handler.seen == [], "the bearer token was carried to another origin"
    assert origin_handler.seen == [("GET", "/internal/ops/reports/"), ("GET", "/via/internal/ops/reports/")]
    assert "a read is never followed to another origin" in str(caught.value)


def test_the_sweep_reports_a_cross_origin_redirect_without_a_traceback_or_a_leak(two_origins) -> None:
    """The operator's view: the CLI names the location and the setting, and exits 1, not a crash."""
    origin, _origin_handler, offsite, offsite_handler = two_origins
    worktree = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": str(worktree / "src"),
        BASE_URL_ENV: _origin_of(origin),
        REPORTS_TOKEN_ENV: READ_TOKEN,
        VERDICTS_TOKEN_ENV: WRITE_TOKEN,
    }

    done = subprocess.run(
        [sys.executable, str(worktree / "scripts" / "ag_ops_triage.py"), "sweep"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    output = done.stdout + done.stderr
    assert offsite_handler.seen == [], "the bearer token was carried to another origin"
    assert "Traceback" not in output
    assert done.stderr.startswith("ERROR: could not look — ")
    assert f"redirected to {_origin_of(offsite)}/internal/ops/reports/" in done.stderr
    assert BASE_URL_ENV in done.stderr
    assert "a read is never followed to another origin" in done.stderr
    assert READ_TOKEN not in output
    assert done.returncode == 1


@pytest.mark.parametrize(
    ("current", "location", "followed"),
    [
        ("http://ag.test/a", "http://AG.test:80/b", True),
        ("https://ag.test/a", "https://ag.test:443/b", True),
        ("http://ag.test:8000/a", "/b", True),
        ("http://ag.test:8000/a", "https://ag.test:8000/b", False),
        ("http://ag.test:8000/a", "http://ag.test:8001/b", False),
        ("http://ag.test/a", "http://evil.test/b", False),
    ],
)
def test_the_redirect_policy_compares_scheme_host_and_effective_port(current, location, followed) -> None:
    request = urllib.request.Request(current, headers={"Authorization": f"Bearer {READ_TOKEN}"})
    newurl = urllib.parse.urljoin(current, location)

    answer = _RedirectPolicy().redirect_request(request, io.BytesIO(), 302, "Found", email.message.Message(), newurl)

    assert (answer is not None) is followed
