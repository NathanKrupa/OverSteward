# ABOUTME: INNER connector for aigranthelper's /internal/ops/ surface — named reports and bulk verdicts.
# ABOUTME: Tokens are injected via __init__; only client_from_env() reads the environment (ARCH-020).

"""One external system: the AG operator seam behind ``/internal/ops/``.

No decisions live here. It fetches, posts, and maps each transport failure to
the one of three exceptions that says what happened — the split the whole tool
is built on:

- :class:`AgOpsConfigError` — nothing was configured to look. The token is
  absent from this repo, or the *producer* answers "endpoint not configured".
- :class:`AgOpsUnavailableError` — we tried to look and could not. A dead
  source, a timeout, a throttle, an unparseable body.
- :class:`AgOpsNotFoundError` — the path is not there. What that *means*
  (undeployed surface versus registry drift) is the service's call, not this
  layer's, because only the service knows whether a manifest promised it.

The producer's two 503s are deliberately distinguishable and must stay so: an
unprovisioned token answers ``{"error": ...}``, while a store that went dark
answers RFC 9457 problem details naming the ``source``. Collapsing them would
make an unconfigured estate look like a broken one — or worse, the reverse.

**Not every answer comes from the producer.** ``aigranthelper.com`` sits
behind Cloudflare, which blocks the default ``Python-urllib/3.x`` User-Agent at
the edge with a 403 the application never sees (OS#394 — measured: ``error code:
1010``, ``text/plain``). Hence the two rules below:

- Every request announces :data:`USER_AGENT`, so the estate's own tooling is
  identifiable at the edge rather than lumped in with scripted traffic.
- **A verdict about our credential or the producer's own configuration
  requires the producer's JSON envelope.** A 401/403/503 whose body does not
  parse as a JSON object never reached Django, so it says nothing about our
  token — reporting it as "credential rejected" sends the operator to rotate a
  secret that was never checked. 404 is exempt: it makes no such claim, and
  Django's own 404 page *is* HTML (measured against production, and pinned by
  ``test_an_html_404_is_still_not_found...``), so requiring JSON there would
  turn an honest "surface not mounted" into a false edge report.

**A write is never re-sent to a redirect.** ``www.aigranthelper.com`` answers
every path with a Cloudflare 301 to the apex, and urllib follows a 301, 302
or 303 on a POST by re-issuing it as a bodiless GET — which the verdicts endpoint
refuses with a 405 (OS#633). The default address is therefore the apex, and the
default opener stops at any 3xx answering a write, reporting where it was sent
so the operator can point :data:`BASE_URL_ENV` there. Reads still follow a
same-origin redirect: a GET survives one intact.

**A read is never followed to another origin.** urllib copies every header but
``Content-Length`` and ``Content-Type`` onto a followed request, the bearer
token included, so following a GET off the configured origin (scheme, host and
port) would hand the token to whatever the ``Location`` names (OS#719). The
default opener follows a same-origin redirect and refuses a cross-origin one,
reporting the location and :data:`BASE_URL_ENV` as a refused write is
reported. It refuses rather than following with the header stripped: a strip
would turn a misconfigured base URL into a 401 from the other host, which reads
as a rejected credential, where the refusal names the setting to change.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

# Repo root: src/oversteward/ag_ops/client.py -> up three parents.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOTENV_PATH = _REPO_ROOT / ".env"

REPORTS_TOKEN_ENV = "OPS_REPORTS_TOKEN"
VERDICTS_TOKEN_ENV = "OPS_VERDICTS_TOKEN"
BASE_URL_ENV = "AG_OPS_BASE_URL"

DEFAULT_BASE_URL = "https://aigranthelper.com"
DEFAULT_TIMEOUT = 30.0

#: This tool's version, carried in :data:`USER_AGENT`. Bump it when the request
#: shape changes in a way an edge rule or an access log should be able to tell
#: apart — it is the estate's signature at AG's front door, not a wire contract.
CLIENT_VERSION = "1.0"

#: Sent on every request. urllib's default ``Python-urllib/3.x`` is blocked by
#: Cloudflare before the application sees it (OS#394), so a real name here is
#: what makes the tool reachable *and* what makes it identifiable in AG's logs.
USER_AGENT = f"oversteward-ag-ops-triage/{CLIENT_VERSION}"

MANIFEST_PATH = "/internal/ops/reports/"
REPORT_PATH = "/internal/ops/reports/{name}/"
VERDICTS_PATH = "/internal/ops/verdicts/"

#: Problem-details member the producer sets on every RFC 9457 failure. Its
#: presence is what separates "the store went dark" from "no token is set".
_PROBLEM_SOURCE_KEY = "source"
#: The plain-JSON error envelope the shared bearer scheme answers with.
_ERROR_KEY = "error"

_GET = "GET"
_POST = "POST"

_HTTP_REDIRECTS = range(300, 400)
_DEFAULT_PORTS = {"http": 80, "https": 443}
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_UNAVAILABLE = 503
#: The statuses whose meaning is a claim about our credential or the producer's
#: configuration — the ones only the producer's JSON envelope may back.
_PRODUCER_VERDICT_STATUSES = (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN, _HTTP_UNAVAILABLE)


class AgOpsConfigError(RuntimeError):
    """Nothing was configured to look — a missing token here, or an unprovisioned one there."""


class AgOpsUnavailableError(RuntimeError):
    """The seam could not be read or written.

    Deliberately distinct from "there was nothing to report": a sweep that could
    not look must never render like a sweep that looked and found nothing.
    """


class AgOpsNotFoundError(AgOpsUnavailableError):
    """The producer has no such path. The service decides what that means."""


class AgOpsClient:
    """Talks to exactly one external system: aigranthelper's internal ops surface.

    Two scoped tokens, because the producer publishes two: the read token can
    enumerate and pull reports, the write token can record verdicts, and a leak
    of the first moves no rows. Either may be absent — the method that needs a
    missing one is the method that refuses.
    """

    def __init__(
        self,
        *,
        reports_token: str = "",
        verdicts_token: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Callable | None = None,
    ) -> None:
        self._reports_token = reports_token
        self._verdicts_token = verdicts_token
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = opener if opener is not None else _default_opener()

    def manifest(self) -> dict:
        """Every report this producer offers, with the contract version it serves."""
        return self._request(MANIFEST_PATH, token=self._read_token())

    def report(self, name: str, *, since: str = "", limit: int = 0) -> dict:
        """One named report's envelope. ``since`` is ISO-8601; ``limit`` caps the page."""
        path = REPORT_PATH.format(name=urllib.parse.quote(name))
        query = _query_string(since, limit)
        return self._request(f"{path}{query}", token=self._read_token())

    def post_verdicts(self, verdicts: list[dict]) -> dict:
        """Record a batch of verdicts, answering the producer's per-item results."""
        return self._request(
            VERDICTS_PATH,
            token=self._write_token(),
            method=_POST,
            payload={"verdicts": verdicts},
        )

    def _read_token(self) -> str:
        if not self._reports_token:
            raise AgOpsConfigError(
                f"{REPORTS_TOKEN_ENV} is not set — the AG ops sweep needs the read-scope "
                f"bearer token. Export it or add it to the OverSteward repo-root .env."
            )
        return self._reports_token

    def _write_token(self) -> str:
        if not self._verdicts_token:
            raise AgOpsConfigError(
                f"{VERDICTS_TOKEN_ENV} is not set — recording verdicts needs the write-scope "
                f"bearer token. Export it or add it to the OverSteward repo-root .env."
            )
        return self._verdicts_token

    def _request(self, path: str, *, token: str, method: str = _GET, payload: dict | None = None) -> dict:
        """One HTTP round-trip. Failures surface as this module's errors, never as a token."""
        request = urllib.request.Request(  # noqa: SEC-006 — base_url is injected config, not user input
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
        )
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        where = f"({method} {path}): "
        try:
            with self._opener(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise _from_http_error(exc, where, method) from None
        except urllib.error.URLError as exc:
            raise AgOpsUnavailableError(f"AG ops unreachable {where}{exc.reason}") from None
        except OSError as exc:
            raise AgOpsUnavailableError(f"AG ops read failed {where}{exc}") from None
        return _decode(body, where)


class _RedirectPolicy(urllib.request.HTTPRedirectHandler):
    """Follows a same-origin redirect for a read; any other lets the 3xx surface as an error.

    Returning ``None`` from :meth:`redirect_request` declines the redirect; no
    other handler takes it, so urllib's default error handler raises the 3xx as
    an :class:`urllib.error.HTTPError` carrying the ``Location`` header instead
    of re-issuing it — as a bodiless GET for a write, or with the bearer token
    to another origin for a read. The loopback tests in ``tests/ag_ops`` pin this.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_method() != _GET or not _same_origin(req.full_url, newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _same_origin(current: str, target: str) -> bool:
    """Whether ``target`` (absolute, or relative to ``current``) shares its scheme, host and port.

    A port ``urlsplit`` cannot read (out of range, not a number) raises
    ``ValueError``; such a URL is not provably this origin, so it is another one.
    """
    try:
        return _origin(current) == _origin(urllib.parse.urljoin(current, target))
    except ValueError:
        return False


def _origin(url: str) -> tuple[str, str, int | None]:
    """A URL's origin, with the scheme's default port written out so ``:80`` matches its absence."""
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or ""), parts.port or _DEFAULT_PORTS.get(scheme)


def _default_opener() -> Callable:
    """urllib's opener with :class:`_RedirectPolicy` in place of its redirect handler."""
    return urllib.request.build_opener(_RedirectPolicy()).open


def _query_string(since: str, limit: int) -> str:
    """The cursor and page size as a query string — empty when neither was asked for."""
    params = {}
    if since:
        params["since"] = since
    if limit:
        params["limit"] = str(limit)
    return f"?{urllib.parse.urlencode(params)}" if params else ""


def _from_http_error(
    exc: urllib.error.HTTPError, where: str, method: str
) -> AgOpsUnavailableError | AgOpsConfigError:
    """Map one HTTP failure to the exception that says what actually happened.

    ``where`` is the call site as a message prefix — never a credential.
    """
    if exc.code in _HTTP_REDIRECTS:
        return _unfollowed_redirect(exc, where, method)
    body = _error_body(exc)
    if exc.code == _HTTP_NOT_FOUND:
        return AgOpsNotFoundError(f"AG ops has no such path (HTTP 404) {where}{_detail(body or {})}")
    if body is None and exc.code in _PRODUCER_VERDICT_STATUSES:
        return _edge_interference(exc, where)
    if body is None:
        return AgOpsUnavailableError(
            f"AG ops returned HTTP {exc.code} ({_content_type(exc)}) {where}"
            f"with a body that is not the producer's JSON envelope."
        )
    if exc.code == _HTTP_UNAVAILABLE:
        return _from_unavailable(body, where)
    if exc.code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
        return AgOpsConfigError(
            f"AG ops rejected our credential (HTTP {exc.code}) {where}"
            f"— the token in .env does not match the producer's setting."
        )
    return AgOpsUnavailableError(f"AG ops returned HTTP {exc.code} {where}{_detail(body)}")


def _unfollowed_redirect(exc: urllib.error.HTTPError, where: str, method: str) -> AgOpsUnavailableError:
    """A 3xx that reached us: say where it pointed, and which setting to change.

    On a write, or a read sent to another origin, it is :class:`_RedirectPolicy`
    declining. On a same-origin read urllib itself gave up — a redirect loop,
    more redirects than it follows, or no ``Location`` — so the message must not
    claim a refusal.
    """
    headers = getattr(exc, "headers", None)
    named = headers.get("Location", "") if headers else ""
    location = named or "an unnamed location"
    if method == _GET and not _same_origin(exc.url, named):
        why = "a read is never followed to another origin: urllib would re-send the bearer token there."
    elif method == _GET:
        why = "the redirect chain never reached an answer (a loop, too many hops, or no location)."
    else:
        why = "a write is never re-sent to a redirect: urllib would re-issue it as a bodiless GET."
    return AgOpsUnavailableError(
        f"AG ops answered with a redirect that was not followed (HTTP {exc.code}) {where}"
        f"redirected to {location}; set {BASE_URL_ENV} to the address that answers it — {why}"
    )


def _edge_interference(exc: urllib.error.HTTPError, where: str) -> AgOpsUnavailableError:
    """The failure of something in front of the producer — a CDN, a proxy, a WAF.

    Raised whenever a status that would otherwise be a verdict about our
    credential or the producer's configuration arrives *without* the producer's
    JSON envelope. Nothing was checked against our token, and the message says
    so: the operator's next move is to look at the edge, not to rotate a secret.
    """
    return AgOpsUnavailableError(
        f"AG ops request was stopped before it reached the producer "
        f"(HTTP {exc.code}, {_content_type(exc)}) {where}"
        f"the body is not the producer's JSON envelope, so this is the edge (CDN/WAF) "
        f"answering, not aigranthelper — no credential was checked."
    )


def _content_type(exc: urllib.error.HTTPError) -> str:
    """What the intercepting layer said it was sending, for a message to name."""
    headers = getattr(exc, "headers", None)
    return (headers.get("Content-Type", "") if headers else "") or "no content-type"


def _from_unavailable(body: dict, where: str) -> AgOpsUnavailableError | AgOpsConfigError:
    """Split the producer's two 503s: an unprovisioned token versus a source that went dark.

    Problem details name a ``source``; the bearer scheme's unconfigured answer
    carries only ``error``. A body we cannot read at all is the pessimistic
    case — "could not look" — because claiming "not configured" would retire an
    outage into a shrug.
    """
    if _PROBLEM_SOURCE_KEY in body:
        return AgOpsUnavailableError(f"AG ops source unreadable (HTTP 503) {where}{_detail(body)}")
    message = body.get(_ERROR_KEY, "")
    if message:
        return AgOpsConfigError(f"the producer is not configured (HTTP 503) {where}{message}")
    return AgOpsUnavailableError(f"AG ops returned HTTP 503 with no diagnosis {where}")


def _error_body(exc: urllib.error.HTTPError) -> dict | None:
    """The failure body as the producer's JSON object, or ``None`` when it is not one.

    ``None`` is the load-bearing answer: it means whatever answered was not
    speaking the producer's envelope, which is what :func:`_edge_interference`
    exists to report. Collapsing it to ``{}`` is how an edge block became a
    credential verdict (OS#394).
    """
    try:
        payload = json.loads(exc.read())
    except (OSError, ValueError, AttributeError):
        return None
    return payload if isinstance(payload, dict) else None


def _detail(body: dict) -> str:
    """What the producer said about the failure, as a message suffix."""
    return str(body.get("detail") or body.get(_ERROR_KEY) or "")


def _decode(body: bytes, where: str) -> dict:
    """Parse one response body, or say plainly that it was unreadable."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AgOpsUnavailableError(f"AG ops sent unparseable JSON {where}{exc}") from None
    if not isinstance(payload, dict):
        raise AgOpsUnavailableError(f"AG ops sent a non-object body {where}{type(payload).__name__}")
    return payload


def client_from_env(
    env: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
    *,
    opener: Callable | None = None,
) -> AgOpsClient:
    """Factory: build a client around the configured tokens and base URL (ARCH-020).

    This is the only place that touches ``os.environ``. A value not already
    exported falls back to the OverSteward repo-root ``.env``, parsed in-process
    — never shell-sourced (credential-hygiene.md). An exported value wins over
    ``.env``, matching ``load_dotenv``'s ``override=False`` default. Absent
    tokens are not an error here: the method that needs one refuses, so a sweep
    never fails over a write token it was never going to use.
    """
    source = env if env is not None else os.environ
    return AgOpsClient(
        reports_token=_setting(source, REPORTS_TOKEN_ENV, dotenv_path),
        verdicts_token=_setting(source, VERDICTS_TOKEN_ENV, dotenv_path),
        base_url=_setting(source, BASE_URL_ENV, dotenv_path) or DEFAULT_BASE_URL,
        opener=opener,
    )


def _setting(source, name: str, dotenv_path: Path | None) -> str:
    """One configuration value: the exported environment first, then the repo ``.env``.

    ``dotenv_values`` parses without mutating the process environment, and the
    exported value is consulted first — the ``load_dotenv(override=False)``
    ordering, without ever handing a secret to the shell.
    """
    exported = source.get(name)
    if exported:
        return exported
    path = dotenv_path if dotenv_path is not None else _DEFAULT_DOTENV_PATH
    if not path.is_file():
        return ""
    from dotenv import dotenv_values  # noqa: PLC0415 — optional dep, imported lazily

    return dotenv_values(path).get(name) or ""
