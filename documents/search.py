"""Search indexed documents in OpenSearch."""

from typing import Any

from documents.index_manager import ensure_document_index
from documents.search_client import get_opensearch_client


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
                "fields": ["external_id", "data.name^3", "data.category"],
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
        },
    )

    hits = response["hits"]
    return {
        "total": hits["total"]["value"],
        "page": page,
        "page_size": page_size,
        "results": [hit["_source"] for hit in hits["hits"]],
    }
