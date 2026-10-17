"""Create and manage versioned OpenSearch indexes."""

import os

from documents.search_client import get_opensearch_client

INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "indexforge-documents-v1")

DOCUMENT_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "id": {"type": "keyword"},
        "collection_id": {"type": "keyword"},
        "external_id": {"type": "keyword"},
        "version": {"type": "long"},
        "is_deleted": {"type": "boolean"},
        "data": {"type": "object", "dynamic": True},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
    },
}


def ensure_document_index() -> str:
    """Create the document index if it does not exist."""
    client = get_opensearch_client()

    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(
            index=INDEX_NAME,
            body={
                "mappings": DOCUMENT_MAPPING,
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                },
            },
        )

    return INDEX_NAME
