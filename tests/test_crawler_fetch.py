"""Safety tests for bounded HTTP fetching."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from documents.management.commands.crawl_site import (
    MAX_RESPONSE_BYTES,
    fetch_limited,
)


@pytest.fixture
def client():
    with httpx.Client(trust_env=False) as test_client:
        yield test_client


def make_response(
    status_code=200,
    body=b"<html><title>Example</title><body>Hello</body></html>",
    headers=None,
):
    request = httpx.Request("GET", "https://example.com/")
    response_headers = {"content-type": "text/html; charset=utf-8"}
    if headers:
        response_headers.update(headers)

    return httpx.Response(
        status_code,
        request=request,
        headers=response_headers,
        content=body,
    )


def mock_stream(client, response):
    context = MagicMock()
    context.__enter__.return_value = response
    return patch.object(client, "stream", return_value=context)


def test_fetch_limited_accepts_html(client):
    body = b"<html><title>Example</title></html>"
    response = make_response(body=body)

    with mock_stream(client, response):
        returned_response, returned_body = fetch_limited(client, "https://example.com/")

    assert returned_response is response
    assert returned_body == body


def test_fetch_limited_rejects_non_html(client):
    response = make_response(
        body=b'{"message":"not HTML"}',
        headers={"content-type": "application/json"},
    )

    with mock_stream(client, response):
        with pytest.raises(ValueError, match="not HTML"):
            fetch_limited(client, "https://example.com/")


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_fetch_limited_rejects_redirects(client, status_code):
    response = make_response(
        status_code=status_code,
        headers={"location": "/other-page"},
    )

    with (
        mock_stream(client, response),
        patch("documents.management.commands.crawl_site.validate_public_host") as validate_host,
    ):
        with pytest.raises(ValueError, match="Redirect encountered"):
            fetch_limited(client, "https://example.com/")

    validate_host.assert_called_once_with("https://example.com/other-page")


def test_fetch_limited_rejects_redirect_without_location(client):
    response = make_response(
        status_code=302,
        headers={"location": ""},
    )

    with mock_stream(client, response):
        with pytest.raises(ValueError, match="did not provide a destination"):
            fetch_limited(client, "https://example.com/")


def test_fetch_limited_rejects_redirect_to_non_http_scheme(client):
    response = make_response(
        status_code=302,
        headers={"location": "file:///etc/passwd"},
    )

    with (
        mock_stream(client, response),
        patch("documents.management.commands.crawl_site.validate_public_host") as validate_host,
    ):
        with pytest.raises(ValueError, match="Only HTTP and HTTPS"):
            fetch_limited(client, "https://example.com/")

    validate_host.assert_not_called()


def test_fetch_limited_rejects_oversized_declared_content_length(client):
    response = make_response(headers={"content-length": str(MAX_RESPONSE_BYTES + 1)})

    with mock_stream(client, response):
        with pytest.raises(ValueError, match="2 MB response limit"):
            fetch_limited(client, "https://example.com/")


def test_fetch_limited_rejects_malformed_content_length(client):
    response = make_response(headers={"content-length": "not-a-number"})

    with mock_stream(client, response):
        with pytest.raises(ValueError):
            fetch_limited(client, "https://example.com/")


def test_fetch_limited_rejects_body_over_limit(client):
    response = make_response(body=b"x" * (MAX_RESPONSE_BYTES + 1))

    with mock_stream(client, response):
        with pytest.raises(ValueError, match="2 MB response limit"):
            fetch_limited(client, "https://example.com/")


def test_fetch_limited_rejects_http_error_status(client):
    response = make_response(status_code=500)

    with mock_stream(client, response):
        with pytest.raises(httpx.HTTPStatusError):
            fetch_limited(client, "https://example.com/")
