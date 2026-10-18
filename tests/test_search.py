"""Tests for document search relevance and result previews."""

from unittest.mock import patch

import pytest

from documents.search import search_documents


@pytest.fixture
def search_response():
    return {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_score": 10.0,
                    "_source": {
                        "id": "document-1",
                        "external_id": "https://example.com/docs",
                        "collection_id": "collection-1",
                        "is_deleted": False,
                        "data": {
                            "title": "IndexForge Documentation",
                            "content": (
                                "Learn how IndexForge indexes searchable "
                                "documents and their source URLs."
                            ),
                            "url": "https://example.com/docs",
                        },
                    },
                    "highlight": {
                        "data.title": [
                            "IndexForge <em>Documentation</em>",
                        ],
                        "data.content": [
                            "Learn how IndexForge indexes <em>searchable</em> documents.",
                        ],
                    },
                }
            ],
        }
    }


@pytest.mark.django_db
def test_search_returns_source_url_and_highlighted_snippet(search_response):
    with (
        patch("documents.search.get_opensearch_client") as get_client,
        patch(
            "documents.search.ensure_document_index",
            return_value="indexforge-documents",
        ),
    ):
        get_client.return_value.search.return_value = search_response

        result = search_documents(query="searchable")

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["results"][0]["data"]["url"] == "https://example.com/docs"
    assert result["results"][0]["snippet"] == (
        "Learn how IndexForge indexes <em>searchable</em> documents."
    )

    body = get_client.return_value.search.call_args.kwargs["body"]
    boolean_query = body["query"]["bool"]
    multi_match = boolean_query["must"][0]["multi_match"]

    assert multi_match["query"] == "searchable"
    assert "data.title^5" in multi_match["fields"]
    assert "data.name^3" in multi_match["fields"]
    assert "data.content" in multi_match["fields"]
    assert "external_id" not in multi_match["fields"]
    assert multi_match["operator"] == "or"

    assert {
        "match_phrase": {
            "data.title": {
                "query": "searchable",
                "boost": 10,
            }
        }
    } in boolean_query["should"]

    assert body["highlight"]["fields"]["data.content"]["number_of_fragments"] == 1


@pytest.mark.django_db
def test_search_uses_content_excerpt_when_no_highlight_is_returned(
    search_response,
):
    hit = search_response["hits"]["hits"][0]
    hit.pop("highlight")

    with (
        patch("documents.search.get_opensearch_client") as get_client,
        patch(
            "documents.search.ensure_document_index",
            return_value="indexforge-documents",
        ),
    ):
        get_client.return_value.search.return_value = search_response

        result = search_documents(query="IndexForge")

    assert result["results"][0]["snippet"].startswith(
        "Learn how IndexForge indexes searchable documents"
    )


@pytest.mark.django_db
def test_search_uses_unicode_ellipsis_for_long_fallback_snippet(
    search_response,
):
    hit = search_response["hits"]["hits"][0]
    hit.pop("highlight")
    hit["_source"]["data"]["content"] = "word " * 60

    with (
        patch("documents.search.get_opensearch_client") as get_client,
        patch(
            "documents.search.ensure_document_index",
            return_value="indexforge-documents",
        ),
    ):
        get_client.return_value.search.return_value = search_response

        result = search_documents(query="IndexForge")

    snippet = result["results"][0]["snippet"]

    assert len(snippet) == 201
    assert snippet.endswith("…")
    assert not snippet.endswith("â€¦")


@pytest.mark.django_db
def test_search_applies_collection_filter_and_pagination(search_response):
    with (
        patch("documents.search.get_opensearch_client") as get_client,
        patch(
            "documents.search.ensure_document_index",
            return_value="indexforge-documents",
        ),
    ):
        get_client.return_value.search.return_value = search_response

        search_documents(
            query="IndexForge",
            collection_id="collection-1",
            page=2,
            page_size=20,
        )

    body = get_client.return_value.search.call_args.kwargs["body"]

    assert body["from"] == 20
    assert body["size"] == 20
    assert {"term": {"collection_id": "collection-1"}} in (body["query"]["bool"]["filter"])
    assert {"term": {"is_deleted": False}} in body["query"]["bool"]["filter"]


@pytest.mark.django_db
def test_search_clamps_pagination_limits(search_response):
    with (
        patch("documents.search.get_opensearch_client") as get_client,
        patch(
            "documents.search.ensure_document_index",
            return_value="indexforge-documents",
        ),
    ):
        get_client.return_value.search.return_value = search_response

        search_documents(query="", page=-1, page_size=100)

    body = get_client.return_value.search.call_args.kwargs["body"]

    assert body["from"] == 0
    assert body["size"] == 50
    assert body["query"]["bool"]["must"] == [{"match_all": {}}]
    assert body["query"]["bool"]["should"] == []
