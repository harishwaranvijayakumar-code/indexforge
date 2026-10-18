"""Validation helpers for dashboard crawl requests."""

from urllib.parse import urlparse

from django.utils.text import slugify

from documents.management.commands.crawl_site import (
    MAX_PAGES_LIMIT,
    normalize_url,
)


def validate_crawl_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    raw_url = payload.get("seed_url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("Enter a starting URL.")

    try:
        seed_url = normalize_url(raw_url)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if not urlparse(seed_url).hostname:
        raise ValueError("Enter a valid public website URL.")

    raw_pages = payload.get("max_pages", 5)
    if isinstance(raw_pages, bool) or not isinstance(raw_pages, int):
        raise ValueError("Page limit must be a whole number.")

    if not 1 <= raw_pages <= MAX_PAGES_LIMIT:
        raise ValueError("Page limit must be between 1 and 10.")

    raw_name = payload.get("collection_name", "Web Search")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("Collection name is required.")

    collection_name = raw_name.strip()
    if len(collection_name) > 120:
        raise ValueError("Collection name must be 120 characters or fewer.")

    raw_slug = payload.get("collection_slug") or collection_name
    if not isinstance(raw_slug, str):
        raise ValueError("Collection slug must be text.")

    collection_slug = slugify(raw_slug)[:120]
    if not collection_slug:
        raise ValueError("Enter a valid collection name or slug.")

    return {
        "seed_url": seed_url,
        "collection_slug": collection_slug,
        "collection_name": collection_name,
        "max_pages": raw_pages,
    }
