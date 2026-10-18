"""Tests for robots.txt handling."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from documents.management.commands.crawl_site import (
    USER_AGENT,
    get_robot_parser,
)


@pytest.fixture
def client():
    with httpx.Client(trust_env=False) as test_client:
        yield test_client


def make_response(status_code, body=b"", content_type="text/plain"):
    request = httpx.Request("GET", "https://example.com/robots.txt")
    return httpx.Response(
        status_code,
        request=request,
        headers={"content-type": content_type},
        content=body,
    )


def mock_stream(client, response):
    context = MagicMock()
    context.__enter__.return_value = response
    return patch.object(client, "stream", return_value=context)


def test_robots_txt_parses_disallow_rules(client):
    response = make_response(
        200,
        b"User-agent: *\nDisallow: /private\n",
    )

    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        mock_stream(client, response),
    ):
        parser = get_robot_parser(client, "https://example.com/")

    assert parser.can_fetch(USER_AGENT, "https://example.com/public")
    assert not parser.can_fetch(USER_AGENT, "https://example.com/private")


def test_robots_txt_404_allows_crawl(client):
    response = make_response(404)

    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        mock_stream(client, response),
    ):
        parser = get_robot_parser(client, "https://example.com/")

    assert parser.can_fetch(USER_AGENT, "https://example.com/page")


def test_robots_txt_server_error_blocks_crawl(client):
    response = make_response(503)

    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        mock_stream(client, response),
    ):
        parser = get_robot_parser(client, "https://example.com/")

    assert not parser.can_fetch(USER_AGENT, "https://example.com/page")


def test_robots_txt_network_error_blocks_crawl(client):
    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        patch.object(
            client,
            "stream",
            side_effect=httpx.ConnectError("connection failed"),
        ),
    ):
        parser = get_robot_parser(client, "https://example.com/")

    assert not parser.can_fetch(USER_AGENT, "https://example.com/page")


def test_robots_txt_oversized_content_blocks_crawl(client):
    response = make_response(
        200,
        b" " * (512 * 1024 + 1),
    )

    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        mock_stream(client, response),
    ):
        parser = get_robot_parser(client, "https://example.com/")

    assert not parser.can_fetch(USER_AGENT, "https://example.com/page")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:443/",
        "https://example.com:80/",
        "https://example.com:8443/",
        "https://example.com:not-a-port/",
    ],
)
def test_normalize_url_rejects_invalid_or_nonstandard_ports(url):
    from documents.management.commands.crawl_site import normalize_url

    with pytest.raises(ValueError):
        normalize_url(url)
