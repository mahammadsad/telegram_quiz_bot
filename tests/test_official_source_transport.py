"""Exercise the real urllib redirect/error machinery with no network access."""

from email.message import Message
from io import BytesIO
from urllib import request
from urllib.response import addinfourl

import pytest

from scripts import refresh_current_affairs_sources as source

ORIGIN = "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2290999"


@pytest.fixture
def transport(monkeypatch):
    calls = []
    redirects = {}
    replies = []
    failures = []
    original_build = request.build_opener

    class Body(BytesIO):
        def __init__(self, payload):
            super().__init__(payload)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    def respond(req):
        calls.append(req.full_url)
        configured = failures.pop(0) if failures else {}
        if isinstance(configured, int):
            configured = {"status": configured}
        headers = Message()
        headers["Content-Type"] = configured.get("content_type", "text/html; charset=utf-8")
        status = configured.get("status", 302 if req.full_url in redirects else 200)
        if req.full_url in redirects:
            headers["Location"] = redirects[req.full_url]
        body = Body(configured.get("body", b"Verified public release text"))
        response = addinfourl(body, headers, req.full_url, status)
        response.msg = "Response"
        replies.append((status, body))
        return response

    class HTTPS(request.HTTPSHandler):
        def https_open(self, req):
            return respond(req)

    class HTTP(request.HTTPHandler):
        def http_open(self, req):
            return respond(req)

    def build(*handlers):
        return original_build(*handlers, HTTPS(), HTTP(), request.ProxyHandler({}))

    monkeypatch.setattr(request, "build_opener", build)
    monkeypatch.setattr(request, "_opener", build())
    monkeypatch.setattr(source, "FETCH_RETRY_DELAY_SECONDS", 0)
    return calls, redirects, replies, failures


@pytest.mark.parametrize("target", [
    "https://127.0.0.1/private",
    "https://pib.gov.in.evil.example/release",
    "https://www.rbi.org.in/release",
    "http://www.pib.gov.in/release",
    "https://www.pib.gov.in:8443/release",
    "https://user:password@www.pib.gov.in/release",
    "https://[broken/release",
])
def test_redirect_target_is_rejected_before_contact(transport, target):
    calls, redirects, replies, _ = transport
    redirects[ORIGIN] = target
    with pytest.raises(source.CurrentAffairsRefreshError):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN]
    assert all(body.closed for _, body in replies)


@pytest.mark.parametrize("url", [
    "http://www.pib.gov.in/release", "https://www.pib.gov.in:8443/release",
    "https://user:password@www.pib.gov.in/release", "https://evil.example/release",
])
def test_invalid_initial_url_never_reaches_transport(transport, url):
    calls, _, _, _ = transport
    with pytest.raises(source.CurrentAffairsRefreshError):
        source.fetch_text(url)
    assert calls == []


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_same_authority_and_relative_redirects_succeed_without_reading_redirect_bodies(transport, code):
    calls, redirects, replies, failures = transport
    failures.append(code)
    second = "https://pib.gov.in/first"
    third = "https://pib.gov.in/final"
    redirects.update({ORIGIN: second, second: "/final"})
    assert source.fetch_text(ORIGIN) == "Verified public release text"
    assert calls == [ORIGIN, second, third]
    assert all(body.closed for _, body in replies)
    assert all(body.read_sizes == [] for status, body in replies if 300 <= status < 400)


def test_redirect_loop_is_bounded_without_restarting_the_chain(transport):
    calls, redirects, _, _ = transport
    redirects[ORIGIN] = ORIGIN
    with pytest.raises(source.CurrentAffairsRefreshError):
        source.fetch_text(ORIGIN)
    assert len(calls) <= 6


@pytest.mark.parametrize("transient", [429, 500, 503])
def test_transient_status_retries_and_closes_each_response(transport, transient):
    calls, _, replies, failures = transport
    failures.extend([transient, 200])
    assert source.fetch_text(ORIGIN) == "Verified public release text"
    assert calls == [ORIGIN, ORIGIN]
    assert all(body.closed for _, body in replies)


def test_permanent_rejection_is_not_retried(transport):
    calls, _, replies, failures = transport
    failures.append(403)
    with pytest.raises(source.CurrentAffairsRefreshError):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN]
    assert all(body.closed for _, body in replies)


def test_missing_redirect_target_is_closed_without_retry(transport):
    calls, _, replies, failures = transport
    failures.append(302)
    with pytest.raises(source.CurrentAffairsRefreshError, match="no target"):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN]
    assert all(body.closed and body.read_sizes == [] for _, body in replies)


def test_transient_failure_exhausts_only_the_existing_retry_budget(transport):
    calls, _, replies, failures = transport
    failures.extend([503] * (source.FETCH_ATTEMPTS + 1))
    with pytest.raises(source.CurrentAffairsRefreshError, match="request failed"):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN] * source.FETCH_ATTEMPTS
    assert all(body.closed and body.read_sizes == [] for _, body in replies)


@pytest.mark.parametrize("configuration", [
    {"content_type": "application/pdf"},
    {"content_type": "text/html; charset=invalid-charset"},
    {"body": b"\xff"},
])
def test_invalid_response_content_fails_closed_without_retry(transport, configuration):
    calls, _, replies, failures = transport
    failures.append(configuration)
    with pytest.raises(source.CurrentAffairsRefreshError):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN]
    assert all(body.closed for _, body in replies)


def test_response_read_is_capped_and_oversized_body_is_rejected(transport, monkeypatch):
    calls, _, replies, _ = transport
    monkeypatch.setattr(source, "MAX_RESPONSE_BYTES", 8)
    with pytest.raises(source.CurrentAffairsRefreshError, match="response was rejected"):
        source.fetch_text(ORIGIN)
    assert calls == [ORIGIN]
    assert replies[0][1].read_sizes == [9]
    assert replies[0][1].closed
