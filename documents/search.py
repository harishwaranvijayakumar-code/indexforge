"""Search indexed documents in OpenSearch."""

from typing import Any

from documents.index_manager import ensure_document_index
from documents.search_client import get_opensearch_client


def _build_snippet(hit: dict[str, Any]) -> str:
    """Build a short preview from highlighted matches or source content."""
    highlights = hit.get("highlight", {})

    for field in ("data.content", "data.title", "data.name"):
        fragments = highlights.get(field, [])
        if fragments:
            return fragments[0]

    source = hit.get("_source", {})
    data = source.get("data", {})

    for field in ("content", "title", "name", "url"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            return text[:200] + ("…" if len(text) > 200 else "")

    return ""


def search_documents(
    *,
    query: str,
    collection_id: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Search active indexed documents with bounded pagination."""
    page = max(1, page)
    page_size = min(50, max(1, page_size))

    filters: list[dict[str, Any]] = [
        {"term": {"is_deleted": False}},
    ]
    if collection_id:
        filters.append({"term": {"collection_id": collection_id}})

    if query.strip():
        search_query: dict[str, Any] = {
            "multi_match": {
                "query": query.strip(),
                "fields": [
                    "external_id",
                    "data.title^5",
                    "data.name^3",
                    "data.content",
                    "data.url^2",
                    "data.category",
                ],
                "type": "best_fields",
            }
        }
    else:
        search_query = {"match_all": {}}

    response = get_opensearch_client().search(
        index=ensure_document_index(),
        body={
            "from": (page - 1) * page_size,
            "size": page_size,
            "query": {
                "bool": {
                    "filter": filters,
                    "must": [search_query],
                }
            },
            "sort": [{"_score": "desc"}, {"id": "asc"}],
            "highlight": {
                "fields": {
                    "data.title": {},
                    "data.name": {},
                    "data.content": {
                        "fragment_size": 200,
                        "number_of_fragments": 1,
                    },
                }
            },
        },
    )

    hits = response["hits"]
    results = []

    for hit in hits["hits"]:
        result = dict(hit["_source"])
        result["snippet"] = _build_snippet(hit)
        results.append(result)

    return {
        "total": hits["total"]["value"],
        "page": page,
        "page_size": page_size,
        "results": results,
    }
