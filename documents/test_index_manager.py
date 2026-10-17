"""Tests for OpenSearch index management."""

from unittest.mock import MagicMock, patch

import pytest

from documents.index_manager import (
    ALIAS_NAME,
    DOCUMENT_MAPPING,
    INDEX_NAME,
    ensure_document_index,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Provide a mocked OpenSearch client."""
    client = MagicMock()
    client.indices.exists_alias.return_value = False
    client.indices.exists.return_value = False
    return client


def test_creates_index_and_alias_when_missing(mock_client: MagicMock) -> None:
    with patch(
        "documents.index_manager.get_opensearch_client",
        return_value=mock_client,
    ):
        result = ensure_document_index()

    assert result == ALIAS_NAME
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
    mock_client.indices.update_aliases.assert_called_once_with(
        body={"actions": [{"add": {"index": INDEX_NAME, "alias": ALIAS_NAME}}]}
    )


def test_returns_existing_alias_without_changes(mock_client: MagicMock) -> None:
    mock_client.indices.exists_alias.return_value = True

    with patch(
        "documents.index_manager.get_opensearch_client",
        return_value=mock_client,
    ):
        result = ensure_document_index()

    assert result == ALIAS_NAME
    mock_client.indices.create.assert_not_called()
    mock_client.indices.update_aliases.assert_not_called()


def test_adopts_existing_physical_index_without_recreating_it(
    mock_client: MagicMock,
) -> None:
    mock_client.indices.exists.return_value = True

    with patch(
        "documents.index_manager.get_opensearch_client",
        return_value=mock_client,
    ):
        result = ensure_document_index()

    assert result == ALIAS_NAME
    mock_client.indices.create.assert_not_called()
    mock_client.indices.update_aliases.assert_called_once_with(
        body={"actions": [{"add": {"index": INDEX_NAME, "alias": ALIAS_NAME}}]}
    )
