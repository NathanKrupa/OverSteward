# ABOUTME: Tests the signed live-URL probe client — header carried, challenge recognised, title read.
# ABOUTME: Transport is a fake; nothing here touches the network.

from __future__ import annotations

import io
from urllib.error import HTTPError

from oversteward.probe.client import fetch
from oversteward.probe.models import PROBE_HEADER

_URL = "https://aigranthelper.com/foundations/pa/richard-king-mellon-foundation/"
_TOKEN = "probe-token"


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.status = status
        self._headers = headers or {}

    def getheader(self, name: str, default=None):
        return self._headers.get(name.lower(), default)


def _transport_recording(response):
    seen: list = []

    def transport(request, timeout):
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    return transport, seen


class TestHeader:
    def test_the_probe_header_carries_the_token(self):
        transport, seen = _transport_recording(_Response(b"<title>x</title>"))
        fetch(_URL, _TOKEN, transport=transport)
        # urllib stores header names capitalised; the wire and Cloudflare are case-insensitive.
        assert seen[0].get_header(PROBE_HEADER.capitalize()) == _TOKEN

    def test_the_url_is_fetched_as_given(self):
        transport, seen = _transport_recording(_Response(b""))
        fetch(_URL, _TOKEN, transport=transport)
        assert seen[0].full_url == _URL


class TestResult:
    def test_a_clean_page_reports_status_and_title(self):
        transport, _ = _transport_recording(
            _Response(b"<html><head><title>Richard King Mellon Foundation | AG</title></head>")
        )
        result = fetch(_URL, _TOKEN, transport=transport)
        assert result.status == 200
        assert result.title == "Richard King Mellon Foundation | AG"
        assert result.challenged is False

    def test_a_cloudflare_challenge_is_a_result_not_an_exception(self):
        error = HTTPError(
            _URL,
            403,
            "Forbidden",
            {"cf-mitigated": "challenge"},  # type: ignore[arg-type]
            io.BytesIO(b"<title>Just a moment...</title>"),
        )
        transport, _ = _transport_recording(error)
        result = fetch(_URL, _TOKEN, transport=transport)
        assert result.status == 403
        assert result.challenged is True
        assert result.title == "Just a moment..."

    def test_a_plain_404_is_not_a_challenge(self):
        error = HTTPError(_URL, 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        transport, _ = _transport_recording(error)
        result = fetch(_URL, _TOKEN, transport=transport)
        assert result.status == 404
        assert result.challenged is False

    def test_a_page_without_a_title_reports_empty(self):
        transport, _ = _transport_recording(_Response(b"<html></html>"))
        assert fetch(_URL, _TOKEN, transport=transport).title == ""
