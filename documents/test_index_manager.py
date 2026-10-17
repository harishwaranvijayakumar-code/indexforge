"""Tests for OpenSearch index management."""

from unittest.mock import MagicMock, patch

import pytest

from documents.index_manager import (
    DOCUMENT_MAPPING,
    INDEX_NAME,
    ensure_document_index,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Provide a mocked OpenSearch client."""
    client = MagicMock()
    client.indices.exists.return_value = False
    return client


def test_creates_index_when_missing(mock_client: MagicMock) -> None:
    with patch(
        "documents.index_manager.get_opensearch_client",
        return_value=mock_client,
    ):
        result = ensure_document_index()

    assert result == INDEX_NAME
    mock_client.indices.create.assert_called_once_with(
        index=INDEX_NAME,
        body={
            "mappings": DOCUMENT_MAPPING,
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
        },
    )


def test_does_not_recreate_existing_index(mock_client: MagicMock) -> None:
    mock_client.indices.exists.return_value = True

    with patch(
        "documents.index_manager.get_opensearch_client",
        return_value=mock_client,
    ):
        result = ensure_document_index()

    assert result == INDEX_NAME
    mock_client.indices.create.assert_not_called()
