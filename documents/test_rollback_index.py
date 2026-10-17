"""Tests for safe OpenSearch index rollback."""

from io import StringIO
from unittest.mock import Mock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from documents.management.commands.rollback_index import Command


class RollbackIndexTests(SimpleTestCase):
    """Test rollback behavior without contacting live services."""

    def setUp(self):
        self.command = Command()
        self.command.stdout = StringIO()
        self.command.stderr = StringIO()
        self.client = Mock()
        self.options = {"target": "indexforge-documents-v1"}

    @patch("documents.management.commands.rollback_index.get_opensearch_client")
    def test_rejects_alias_as_target(self, get_client):
        with self.assertRaisesMessage(CommandError, "physical index, not the search alias"):
            self.command.handle(target="indexforge-documents")

        get_client.assert_not_called()

    @patch("documents.management.commands.rollback_index.get_opensearch_client")
    def test_rejects_nonexistent_target(self, get_client):
        get_client.return_value = self.client
        self.client.indices.exists.return_value = False

        with self.assertRaisesMessage(CommandError, "does not exist"):
            self.command.handle(**self.options)

    @patch("documents.management.commands.rollback_index.get_opensearch_client")
    def test_returns_if_target_is_already_active(self, get_client):
        get_client.return_value = self.client
        self.client.indices.exists.return_value = True
        self.client.indices.get_alias.return_value = {"indexforge-documents-v1": {}}

        with patch("documents.management.commands.rollback_index.RebuildCommand") as rebuild_class:
            self.command.handle(**self.options)

        rebuild_class.assert_called_once_with()
        rebuild_class.return_value._replay_events.assert_not_called()
        rebuild_class.return_value._validate_replacement.assert_not_called()
        self.client.indices.update_aliases.assert_not_called()

    @patch("documents.management.commands.rollback_index.get_opensearch_client")
    def test_validation_failure_does_not_switch_alias(self, get_client):
        get_client.return_value = self.client
        self.client.indices.exists.return_value = True
        self.client.indices.get_alias.return_value = {"current-index": {}}

        with (
            patch("documents.management.commands.rollback_index.RebuildCommand") as rebuild_class,
            patch("documents.management.commands.rollback_index.transaction.atomic") as atomic,
            patch(
                "documents.management.commands.rollback_index.acquire_document_write_lock"
            ) as acquire_lock,
        ):
            atomic.return_value.__enter__ = Mock(return_value=None)
            atomic.return_value.__exit__ = Mock(return_value=False)

            rebuild = rebuild_class.return_value
            rebuild._validate_replacement.side_effect = CommandError("Validation failed")

            with self.assertRaisesMessage(CommandError, "Validation failed"):
                self.command.handle(**self.options)

        acquire_lock.assert_called_once_with()
        rebuild._replay_events.assert_called_once_with(self.client, "indexforge-documents-v1")
        self.client.indices.update_aliases.assert_not_called()
