"""Rebuild the search index from PostgreSQL and switch its alias safely."""

from datetime import datetime
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from opensearchpy import ConflictError

from documents.index_manager import (
    ALIAS_NAME,
    DOCUMENT_MAPPING,
    INDEX_NAME,
    ensure_document_index,
)
from documents.models import Document, OutboxEvent
from documents.rebuild_lock import acquire_document_write_lock
from documents.search_client import get_opensearch_client

BATCH_SIZE = 500


class Command(BaseCommand):
    """Build a replacement index and switch the stable alias atomically."""

    help = "Rebuild the OpenSearch index from PostgreSQL with safe alias cutover."

    def handle(self, *args, **options):
        client = get_opensearch_client()
        ensure_document_index()

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        base_name = INDEX_NAME.rsplit("-v", 1)[0]
        new_index = f"{base_name}-v{timestamp}-{uuid4().hex[:8]}"
        old_indices = list(client.indices.get_alias(name=ALIAS_NAME))

        if not old_indices:
            raise CommandError(f"Alias {ALIAS_NAME!r} has no index targets.")

        self.stdout.write(f"Creating replacement index: {new_index}")

        try:
            client.indices.create(
                index=new_index,
                body={
                    "mappings": DOCUMENT_MAPPING,
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                    },
                },
            )

            self._backfill_documents(client, new_index)
            self._replay_events(client, new_index)

            # Source writes use the same transaction-scoped advisory lock.
            with transaction.atomic():
                acquire_document_write_lock()

                # Reconcile every event while source writes are paused.
                self._replay_events(client, new_index)
                client.indices.refresh(index=new_index)
                self._validate_replacement(client, new_index)

                actions = [
                    {"remove": {"index": index, "alias": ALIAS_NAME}} for index in old_indices
                ]
                actions.append({"add": {"index": new_index, "alias": ALIAS_NAME}})
                client.indices.update_aliases(body={"actions": actions})

            indexed_count = client.count(index=new_index)["count"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rebuild complete. Alias {ALIAS_NAME!r} now points "
                    f"to {new_index}. Previous indexes retained: "
                    f"{', '.join(old_indices)}. "
                    f"Physical documents: {indexed_count}."
                )
            )

        except Exception as exc:
            # Keep the replacement if the alias switch actually succeeded.
            try:
                current_targets = client.indices.get_alias(name=ALIAS_NAME)
                if new_index not in current_targets:
                    if client.indices.exists(index=new_index):
                        client.indices.delete(index=new_index)
            except Exception:
                self.stderr.write(
                    "Warning: could not determine alias state or clean up "
                    f"replacement {new_index!r}. Inspect OpenSearch manually."
                )

            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"Index rebuild failed: {exc}") from exc

    def _backfill_documents(self, client, index_name: str) -> None:
        """Copy current source documents into the replacement index."""
        for document in Document.objects.iterator(chunk_size=BATCH_SIZE):
            body = {
                "id": str(document.id),
                "collection_id": str(document.collection_id),
                "external_id": document.external_id,
                "version": document.version,
                "is_deleted": False,
                "data": document.data,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat(),
            }
            client.index(
                index=index_name,
                id=str(document.id),
                body=body,
                version=document.version,
                version_type="external",
            )

    def _replay_events(self, client, index_name: str) -> None:
        """Replay all outbox events using external version protection."""
        events = OutboxEvent.objects.all().order_by("created_at", "id")

        for event in events.iterator(chunk_size=BATCH_SIZE):
            payload = event.payload
            body = {
                "id": str(event.document_id),
                "collection_id": str(event.collection_id_snapshot),
                "external_id": event.document_external_id,
                "version": event.document_version,
                "is_deleted": event.event_type == OutboxEvent.EventType.DELETE,
                "data": payload.get("data", {}),
                "created_at": event.created_at.isoformat(),
                "updated_at": event.created_at.isoformat(),
            }
            try:
                client.index(
                    index=index_name,
                    id=str(event.document_id),
                    body=body,
                    version=event.document_version,
                    version_type="external",
                )
            except ConflictError:
                # An equal or newer version already exists.
                continue

    def _validate_replacement(self, client, index_name: str) -> None:
        """Verify active count and source fields before switching the alias."""
        source_count = Document.objects.count()
        active_response = client.count(
            index=index_name,
            body={"query": {"term": {"is_deleted": False}}},
        )
        active_count = active_response["count"]

        if active_count != source_count:
            raise CommandError(
                "Validation failed: "
                f"PostgreSQL has {source_count} documents, but the "
                f"replacement index has {active_count} active documents."
            )

        batch = []

        for document in Document.objects.iterator(chunk_size=BATCH_SIZE):
            batch.append(document)

            if len(batch) >= BATCH_SIZE:
                self._validate_batch(client, index_name, batch)
                batch = []

        if batch:
            self._validate_batch(client, index_name, batch)

    def _validate_batch(self, client, index_name: str, documents) -> None:
        """Compare indexed identity, version, and data with PostgreSQL."""
        response = client.mget(
            index=index_name,
            body={"ids": [str(document.id) for document in documents]},
        )

        indexed_by_id = {
            item["_id"]: item["_source"]
            for item in response["docs"]
            if item.get("found") and "_source" in item
        }

        for document in documents:
            document_id = str(document.id)
            indexed = indexed_by_id.get(document_id)

            if indexed is None:
                raise CommandError(f"Validation failed: document {document_id} is missing.")

            expected = {
                "id": document_id,
                "collection_id": str(document.collection_id),
                "external_id": document.external_id,
                "version": document.version,
                "is_deleted": False,
                "data": document.data,
            }

            mismatches = [
                field
                for field, expected_value in expected.items()
                if indexed.get(field) != expected_value
            ]

            if mismatches:
                raise CommandError(
                    f"Validation failed for document {document_id}: "
                    f"mismatched fields: {', '.join(mismatches)}."
                )
