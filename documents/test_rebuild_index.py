"""Tests for safe OpenSearch index rebuilding."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from documents.management.commands.rebuild_index import Command
from documents.models import OutboxEvent


class RebuildIndexTests(SimpleTestCase):
    """Test rebuild operations without contacting live services."""

    def setUp(self):
        self.command = Command()
        self.client = Mock()

    def make_document(self):
        return SimpleNamespace(
            id="document-123",
            collection_id="collection-123",
            external_id="external-123",
            version=3,
            data={"name": "Test document"},
            created_at=SimpleNamespace(isoformat=lambda: "2026-10-17T10:00:00+00:00"),
            updated_at=SimpleNamespace(isoformat=lambda: "2026-10-17T11:00:00+00:00"),
        )

    def make_indexed_source(self, document):
        return {
            "id": str(document.id),
            "collection_id": str(document.collection_id),
            "external_id": document.external_id,
            "version": document.version,
            "is_deleted": False,
            "data": document.data,
        }

    @patch("documents.management.commands.rebuild_index.Document.objects")
    def test_backfill_indexes_documents_with_external_versions(self, document_manager):
        document = self.make_document()
        document_manager.iterator.return_value = iter([document])

        self.command._backfill_documents(self.client, "replacement-index")

        self.client.index.assert_called_once_with(
            index="replacement-index",
            id="document-123",
            body={
                **self.make_indexed_source(document),
                "created_at": "2026-10-17T10:00:00+00:00",
                "updated_at": "2026-10-17T11:00:00+00:00",
            },
            version=3,
            version_type="external",
        )

    @patch("documents.management.commands.rebuild_index.OutboxEvent.objects")
    def test_replay_events_writes_delete_tombstones(self, event_manager):
        event = SimpleNamespace(
            document_id="document-123",
            collection_id_snapshot="collection-123",
            document_external_id="external-123",
            document_version=4,
            event_type=OutboxEvent.EventType.DELETE,
            payload={"data": {"name": "Deleted document"}},
            created_at=SimpleNamespace(isoformat=lambda: "2026-10-17T12:00:00+00:00"),
        )
        queryset = event_manager.all.return_value
        queryset.order_by.return_value.iterator.return_value = iter([event])

        self.command._replay_events(self.client, "replacement-index")

        self.client.index.assert_called_once_with(
            index="replacement-index",
            id="document-123",
            body={
                "id": "document-123",
                "collection_id": "collection-123",
                "external_id": "external-123",
                "version": 4,
                "is_deleted": True,
                "data": {"name": "Deleted document"},
                "created_at": "2026-10-17T12:00:00+00:00",
                "updated_at": "2026-10-17T12:00:00+00:00",
            },
            version=4,
            version_type="external",
        )

    @patch("documents.management.commands.rebuild_index.OutboxEvent.objects")
    def test_replay_events_handles_empty_history(self, event_manager):
        queryset = event_manager.all.return_value
        queryset.order_by.return_value.iterator.return_value = iter([])

        self.command._replay_events(self.client, "replacement-index")

        self.client.index.assert_not_called()

    @patch("documents.management.commands.rebuild_index.Document.objects")
    def test_validate_batch_accepts_matching_document(self, document_manager):
        document = self.make_document()
        self.client.mget.return_value = {
            "docs": [
                {
                    "_id": str(document.id),
                    "found": True,
                    "_source": self.make_indexed_source(document),
                }
            ]
        }

        self.command._validate_batch(self.client, "replacement-index", [document])

        self.client.mget.assert_called_once_with(
            index="replacement-index",
            body={"ids": ["document-123"]},
        )

    def test_validate_batch_rejects_missing_document(self):
        document = self.make_document()
        self.client.mget.return_value = {"docs": [{"_id": str(document.id), "found": False}]}

        with self.assertRaisesMessage(CommandError, "document document-123 is missing"):
            self.command._validate_batch(self.client, "replacement-index", [document])

    def test_validate_batch_rejects_mismatched_content(self):
        document = self.make_document()
        indexed = self.make_indexed_source(document)
        indexed["version"] = 2

        self.client.mget.return_value = {
            "docs": [
                {
                    "_id": str(document.id),
                    "found": True,
                    "_source": indexed,
                }
            ]
        }

        with self.assertRaisesMessage(CommandError, "mismatched fields: version"):
            self.command._validate_batch(self.client, "replacement-index", [document])
