"""Create and manage versioned OpenSearch indexes and a stable alias."""

import os

from documents.search_client import get_opensearch_client

INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "indexforge-documents-v1")
ALIAS_NAME = os.getenv("OPENSEARCH_ALIAS", "indexforge-documents")

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


def _create_physical_index(client, index_name: str) -> None:
    """Create a physical index with the document mapping."""
    client.indices.create(
        index=index_name,
        body={
            "mappings": DOCUMENT_MAPPING,
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
        },
    )


def ensure_document_index() -> str:
    """Ensure the stable alias points to an initialized physical index."""
    client = get_opensearch_client()

    if client.indices.exists_alias(name=ALIAS_NAME):
        return ALIAS_NAME

    # Preserve the existing physical index and its data when adopting aliases.
    if client.indices.exists(index=INDEX_NAME):
        client.indices.update_aliases(
            body={
                "actions": [
                    {
                        "add": {
                            "index": INDEX_NAME,
                            "alias": ALIAS_NAME,
                        }
                    }
                ]
            }
        )
        return ALIAS_NAME

    _create_physical_index(client, INDEX_NAME)
    client.indices.update_aliases(
        body={
            "actions": [
                {
                    "add": {
                        "index": INDEX_NAME,
                        "alias": ALIAS_NAME,
                    }
                }
            ]
        }
    )
    return ALIAS_NAME
