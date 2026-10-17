"""Tests for transactional document services."""

from unittest.mock import patch

import pytest
from django.db import IntegrityError

from documents.models import Collection, Document, OutboxEvent
from documents.services import (
    DocumentConflictError,
    DocumentNotFoundError,
    create_document,
    delete_document,
    update_document,
)


@pytest.fixture
def collection() -> Collection:
    return Collection.objects.create(name="Products", slug="products")


@pytest.mark.django_db
def test_create_document_creates_upsert_event(collection: Collection) -> None:
    document = create_document(
        collection=collection,
        external_id="product-1",
        data={"name": "Keyboard"},
    )

    event = OutboxEvent.objects.get(document_id=document.id)

    assert document.version == 1
    assert event.event_type == OutboxEvent.EventType.UPSERT
    assert event.document_version == 1
    assert event.payload["data"] == {"name": "Keyboard"}


@pytest.mark.django_db
def test_duplicate_external_id_is_a_conflict(collection: Collection) -> None:
    create_document(
        collection=collection,
        external_id="product-1",
        data={"name": "Keyboard"},
    )

    with pytest.raises(DocumentConflictError):
        create_document(
            collection=collection,
            external_id="product-1",
            data={"name": "Different keyboard"},
        )

    assert Document.objects.filter(collection=collection).count() == 1
    assert OutboxEvent.objects.filter(collection_id_snapshot=collection.id).count() == 1


@pytest.mark.django_db
def test_update_increments_version_and_creates_event(collection: Collection) -> None:
    document = create_document(
        collection=collection,
        external_id="product-1",
        data={"name": "Keyboard"},
    )

    updated = update_document(
        collection=collection,
        external_id="product-1",
        data={"name": "Ergonomic keyboard"},
    )

    assert updated.id == document.id
    assert updated.version == 2
    assert OutboxEvent.objects.filter(
        document_id=document.id,
        document_version=2,
        event_type=OutboxEvent.EventType.UPSERT,
    ).exists()


@pytest.mark.django_db
def test_delete_keeps_tombstone_event(collection: Collection) -> None:
    document = create_document(
        collection=collection,
        external_id="product-1",
        data={"name": "Keyboard"},
    )

    delete_document(collection=collection, external_id="product-1")

    assert not Document.objects.filter(id=document.id).exists()

    event = OutboxEvent.objects.get(
        document_id=document.id,
        event_type=OutboxEvent.EventType.DELETE,
    )
    assert event.document_version == 2
    assert event.payload["id"] == str(document.id)


@pytest.mark.django_db
def test_update_missing_document_raises(collection: Collection) -> None:
    with pytest.raises(DocumentNotFoundError):
        update_document(
            collection=collection,
            external_id="missing",
            data={"name": "Unknown"},
        )


@pytest.mark.django_db
def test_failed_outbox_insert_rolls_back_document(
    collection: Collection,
) -> None:
    with patch(
        "documents.services._create_outbox_event",
        side_effect=IntegrityError("simulated database constraint failure"),
    ):
        with pytest.raises(IntegrityError):
            create_document(
                collection=collection,
                external_id="product-1",
                data={"name": "Keyboard"},
            )

    assert not Document.objects.filter(
        collection=collection,
        external_id="product-1",
    ).exists()
    assert not OutboxEvent.objects.filter(
        collection_id_snapshot=collection.id,
    ).exists()
