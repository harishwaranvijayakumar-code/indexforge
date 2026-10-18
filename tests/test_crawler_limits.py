"""Tests for crawler page and host limits."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.core.management.base import CommandError

from documents.management.commands.crawl_site import (
    MAX_PAGES_LIMIT,
    Command,
)


@pytest.mark.parametrize("max_pages", [0, -1, 11, MAX_PAGES_LIMIT + 1])
def test_crawler_rejects_invalid_page_limits(max_pages):
    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        pytest.raises(CommandError, match="between 1 and 10"),
    ):
        Command().handle(
            url="https://example.com/",
            collection="web-search",
            collection_name="Web Search",
            max_pages=max_pages,
        )


@pytest.mark.django_db
def test_crawler_respects_page_limit_and_same_host():
    start_url = "https://example.com/"
    second_url = "https://example.com/second"

    pages = {
        start_url: (
            b"""
            <html>
              <title>Start page</title>
              <body>
                <p>Start content</p>
                <a href="/second">Second</a>
                <a href="/second#section">Duplicate second</a>
                <a href="https://other.example/private">Off-host</a>
                <a href="javascript:alert(1)">Unsupported scheme</a>
              </body>
            </html>
            """
        ),
        second_url: (
            b"""
            <html>
              <title>Second page</title>
              <body><p>Second content</p></body>
            </html>
            """
        ),
    }

    def fake_fetch(client, url, **kwargs):
        request = httpx.Request("GET", url)
        response = httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=pages[url],
        )
        return response, pages[url]

    robots = MagicMock()
    robots.can_fetch.return_value = True

    with (
        patch("documents.management.commands.crawl_site.validate_public_host"),
        patch(
            "documents.management.commands.crawl_site.get_robot_parser",
            return_value=robots,
        ),
        patch(
            "documents.management.commands.crawl_site.fetch_limited",
            side_effect=fake_fetch,
        ) as fetch,
        patch(
            "documents.management.commands.crawl_site.REQUEST_DELAY_SECONDS",
            0,
        ),
        patch("documents.management.commands.crawl_site.create_document") as create_document,
        patch("documents.management.commands.crawl_site.update_document") as update_document,
    ):
        Command().handle(
            url=start_url,
            collection="crawler-limits-test",
            collection_name="Crawler Limits Test",
            max_pages=2,
        )

    # Both pages must be fetched in order using the shared request pacer.
    assert fetch.call_count == 2
    assert [invocation.args[1] for invocation in fetch.call_args_list] == [start_url, second_url]
    assert all("pacer" in invocation.kwargs for invocation in fetch.call_args_list)

    # Each page is created once, and neither requires an update.
    assert create_document.call_count == 2
    update_document.assert_not_called()

    indexed_urls = {
        invocation.kwargs["external_id"] for invocation in create_document.call_args_list
    }
    assert indexed_urls == {start_url, second_url}
