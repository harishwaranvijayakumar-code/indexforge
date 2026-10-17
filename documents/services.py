"""Transactional services for document ingestion."""

from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from documents.models import Collection, Document, OutboxEvent


class DocumentConflictError(Exception):
    """Raised when a document conflicts with an existing source record."""


class DocumentNotFoundError(Exception):
    """Raised when the requested document does not exist."""


def _create_outbox_event(
    *,
    collection_id: UUID,
    document_id: UUID,
    external_id: str,
    version: int,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Create an outbox event inside the caller's database transaction."""
    return OutboxEvent.objects.create(
        collection_id_snapshot=collection_id,
        document_id=document_id,
        document_external_id=external_id,
        document_version=version,
        event_type=event_type,
        payload=payload,
    )


def create_document(
    *,
    collection: Collection,
    external_id: str,
    data: dict[str, Any],
) -> Document:
    """Create a source document and its initial indexing event atomically."""
    try:
        with transaction.atomic():
            document = Document.objects.create(
                collection=collection,
                external_id=external_id,
                data=data,
                version=1,
            )
            _create_outbox_event(
                collection_id=collection.id,
                document_id=document.id,
                external_id=document.external_id,
                version=document.version,
                event_type=OutboxEvent.EventType.UPSERT,
                payload={
                    "id": str(document.id),
                    "external_id": document.external_id,
                    "version": document.version,
                    "data": document.data,
                },
            )
            return document
    except IntegrityError as exc:
        if Document.objects.filter(
            collection=collection,
            external_id=external_id,
        ).exists():
            raise DocumentConflictError(
                "A document with this external_id already exists in the collection."
            ) from exc
        raise


def update_document(
    *,
    collection: Collection,
    external_id: str,
    data: dict[str, Any],
) -> Document:
    """Replace document data and emit a versioned indexing event atomically."""
    with transaction.atomic():
        try:
            document = Document.objects.select_for_update().get(
                collection=collection, external_id=external_id
            )
        except Document.DoesNotExist as exc:
            raise DocumentNotFoundError("The requested document does not exist.") from exc

        document.data = data
        document.version += 1
        document.updated_at = timezone.now()
        document.save(update_fields=["data", "version", "updated_at"])

        _create_outbox_event(
            collection_id=collection.id,
            document_id=document.id,
            external_id=document.external_id,
            version=document.version,
            event_type=OutboxEvent.EventType.UPSERT,
            payload={
                "id": str(document.id),
                "external_id": document.external_id,
                "version": document.version,
                "data": document.data,
            },
        )
        return document


def delete_document(
    *,
    collection: Collection,
    external_id: str,
) -> None:
    """Emit a deletion event and remove the source document atomically."""
    with transaction.atomic():
        try:
            document = Document.objects.select_for_update().get(
                collection=collection, external_id=external_id
            )
        except Document.DoesNotExist as exc:
            raise DocumentNotFoundError("The requested document does not exist.") from exc

        deletion_version = document.version + 1

        _create_outbox_event(
            collection_id=collection.id,
            document_id=document.id,
            external_id=document.external_id,
            version=deletion_version,
            event_type=OutboxEvent.EventType.DELETE,
            payload={
                "id": str(document.id),
                "external_id": document.external_id,
                "version": deletion_version,
            },
        )

        document.delete()
