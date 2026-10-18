"""Tests for crawler HTML extraction and document ingestion."""

from io import StringIO
from unittest.mock import MagicMock

import httpx
import pytest
from django.core.management import call_command

from documents.management.commands import crawl_site
from documents.models import Collection, Document, OutboxEvent
from documents.services import create_document

URL = "https://example.com/"
COLLECTION_SLUG = "crawler-extraction-test"


@pytest.fixture
def crawler_setup(monkeypatch, db):
    """Mock network operations while retaining real database ingestion."""
    client = MagicMock()
    robots = MagicMock()
    robots.can_fetch.return_value = True

    monkeypatch.setattr(
        crawl_site,
        "create_safe_client",
        lambda **kwargs: client,
    )
    monkeypatch.setattr(
        crawl_site,
        "validate_public_host",
        lambda url: None,
    )
    monkeypatch.setattr(
        crawl_site,
        "get_robot_parser",
        lambda client, url, **kwargs: robots,
    )
    monkeypatch.setattr(crawl_site.time, "sleep", lambda seconds: None)

    collection = Collection.objects.create(
        slug=COLLECTION_SLUG,
        name="Crawler Extraction Test",
    )

    return collection, client


def run_crawl(monkeypatch, html):
    """Run the crawler with a mocked HTML response."""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", URL),
        headers={"content-type": "text/html"},
    )

    monkeypatch.setattr(
        crawl_site,
        "fetch_limited",
        lambda client, url, **kwargs: (response, html.encode("utf-8")),
    )

    output = StringIO()
    call_command(
        "crawl_site",
        URL,
        collection=COLLECTION_SLUG,
        collection_name="Crawler Extraction Test",
        max_pages=1,
        stdout=output,
    )
    return output.getvalue()


@pytest.mark.django_db
def test_crawler_extracts_html_and_creates_document(
    crawler_setup,
    monkeypatch,
):
    collection, _ = crawler_setup
    html = """
    <html>
      <head><title>Example Documentation</title></head>
      <body>
        <nav>Navigation must be removed</nav>
        <main><h1>Useful page content</h1><p>Searchable text.</p></main>
        <script>secret_script_value()</script>
        <style>.hidden { display: none; }</style>
        <footer>Footer must be removed</footer>
      </body>
    </html>
    """

    output = run_crawl(monkeypatch, html)

    document = Document.objects.get(
        collection=collection,
        external_id=URL,
    )

    assert document.data["title"] == "Example Documentation"
    assert document.data["name"] == "Example Documentation"
    assert document.data["url"] == URL
    assert document.data["category"] == "web-page"
    assert "Useful page content" in document.data["content"]
    assert "Searchable text." in document.data["content"]
    assert "Navigation must be removed" not in document.data["content"]
    assert "Footer must be removed" not in document.data["content"]
    assert "secret_script_value" not in document.data["content"]
    assert "Indexed or updated: 1" in output
    assert OutboxEvent.objects.filter(document_id=document.id).count() == 1


@pytest.mark.django_db
def test_crawler_updates_existing_document_and_emits_event(
    crawler_setup,
    monkeypatch,
):
    collection, _ = crawler_setup

    existing = create_document(
        collection=collection,
        external_id=URL,
        data={"title": "Old title", "content": "Old content"},
    )
    initial_version = existing.version
    initial_events = OutboxEvent.objects.filter(
        document_id=existing.id,
    ).count()

    html = """
    <html>
      <head><title>Updated Documentation</title></head>
      <body><p>Updated searchable content.</p></body>
    </html>
    """

    output = run_crawl(monkeypatch, html)
    existing.refresh_from_db()

    assert existing.version == initial_version + 1
    assert existing.data["title"] == "Updated Documentation"
    assert "Updated searchable content." in existing.data["content"]
    assert (
        OutboxEvent.objects.filter(
            document_id=existing.id,
        ).count()
        == initial_events + 1
    )
    assert "Indexed or updated: 1" in output


@pytest.mark.django_db
def test_crawler_skips_page_with_no_extractable_content(
    crawler_setup,
    monkeypatch,
):
    collection, _ = crawler_setup
    html = """
    <html>
      <body>
        <script>script only</script>
        <style>.empty {}</style>
        <nav>navigation only</nav>
        <footer>footer only</footer>
      </body>
    </html>
    """

    output = run_crawl(monkeypatch, html)

    assert not Document.objects.filter(
        collection=collection,
        external_id=URL,
    ).exists()
    assert "Indexed or updated: 0" in output
    assert "skipped: 1" in output
