"""Tests for the document search API."""

from unittest.mock import patch

import pytest
from django.test import Client

from documents.models import Collection


@pytest.fixture
def collection() -> Collection:
    return Collection.objects.create(name="Products", slug="search-products")


@pytest.mark.django_db
def test_search_returns_results(client: Client, collection: Collection) -> None:
    expected = {
        "total": 1,
        "page": 1,
        "page_size": 10,
        "results": [
            {
                "id": "document-1",
                "external_id": "keyboard-001",
                "is_deleted": False,
            }
        ],
    }

    with patch("documents.views.search_documents", return_value=expected):
        response = client.get(
            "/api/search/",
            {"q": "keyboard", "collection": collection.slug},
        )

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.django_db
def test_search_unknown_collection_returns_404(client: Client) -> None:
    response = client.get(
        "/api/search/",
        {"collection": "does-not-exist"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Collection not found."


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("params", "expected_error"),
    [
        ({"page": "abc"}, "page and page_size must be integers."),
        ({"page": "0"}, "page and page_size must be positive integers."),
        ({"page_size": "-1"}, "page and page_size must be positive integers."),
    ],
)
def test_search_rejects_invalid_pagination(
    client: Client,
    params: dict[str, str],
    expected_error: str,
) -> None:
    response = client.get("/api/search/", params)

    assert response.status_code == 400
    assert response.json()["error"] == expected_error


@pytest.mark.django_db
def test_search_only_accepts_get(client: Client) -> None:
    response = client.post("/api/search/", data={"q": "keyboard"})

    assert response.status_code == 405
