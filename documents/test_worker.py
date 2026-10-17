"""Tests for the OpenSearch outbox worker."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from opensearchpy import ConflictError

from documents.models import Collection, OutboxEvent
from documents.services import create_document
from documents.worker import (
    MAX_ATTEMPTS,
    _write_event,
    claim_events,
    process_event,
)


@pytest.fixture
def collection() -> Collection:
    return Collection.objects.create(name="Products", slug="worker-products")


@pytest.fixture
def pending_event(collection: Collection) -> OutboxEvent:
    document = create_document(
        collection=collection,
        external_id="worker-product-1",
        data={"name": "Keyboard"},
    )
    return OutboxEvent.objects.get(
        document_id=document.id,
        event_type=OutboxEvent.EventType.UPSERT,
    )


@pytest.mark.django_db
def test_claim_events_marks_event_processing(
    pending_event: OutboxEvent,
) -> None:
    event_ids = claim_events(batch_size=1)

    pending_event.refresh_from_db()
    assert event_ids == [pending_event.id]
    assert pending_event.status == OutboxEvent.Status.PROCESSING
    assert pending_event.attempts == 1


@pytest.mark.django_db
def test_process_event_marks_successful_write_processed(
    pending_event: OutboxEvent,
) -> None:
    pending_event.status = OutboxEvent.Status.PROCESSING
    pending_event.attempts = 1
    pending_event.save(update_fields=["status", "attempts"])

    with patch("documents.worker._write_event"):
        assert process_event(pending_event.id) is True

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.PROCESSED
    assert pending_event.processed_at is not None
    assert pending_event.last_error == ""


@pytest.mark.django_db
def test_process_event_retries_failed_write(
    pending_event: OutboxEvent,
) -> None:
    pending_event.status = OutboxEvent.Status.PROCESSING
    pending_event.attempts = 1
    pending_event.save(update_fields=["status", "attempts"])

    with patch(
        "documents.worker._write_event",
        side_effect=RuntimeError("temporary OpenSearch outage"),
    ):
        assert process_event(pending_event.id) is False

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.PENDING
    assert "temporary OpenSearch outage" in pending_event.last_error
    assert pending_event.available_at > timezone.now()


@pytest.mark.django_db
def test_process_event_fails_after_retry_limit(
    pending_event: OutboxEvent,
) -> None:
    pending_event.status = OutboxEvent.Status.PROCESSING
    pending_event.attempts = MAX_ATTEMPTS
    pending_event.save(update_fields=["status", "attempts"])

    with patch(
        "documents.worker._write_event",
        side_effect=RuntimeError("permanent failure"),
    ):
        assert process_event(pending_event.id) is False

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.FAILED


@pytest.mark.django_db
def test_write_event_uses_external_versioning(
    pending_event: OutboxEvent,
) -> None:
    with (
        patch("documents.worker.get_opensearch_client") as get_client,
        patch(
            "documents.worker.ensure_document_index",
            return_value="test-index",
        ),
    ):
        _write_event(pending_event)

    get_client.return_value.index.assert_called_once()
    kwargs = get_client.return_value.index.call_args.kwargs
    assert kwargs["version"] == pending_event.document_version
    assert kwargs["version_type"] == "external"
    assert kwargs["body"]["is_deleted"] is False


@pytest.mark.django_db
def test_stale_version_conflict_is_treated_as_complete(
    pending_event: OutboxEvent,
) -> None:
    with (
        patch("documents.worker.get_opensearch_client") as get_client,
        patch(
            "documents.worker.ensure_document_index",
            return_value="test-index",
        ),
    ):
        get_client.return_value.index.side_effect = ConflictError(
            409,
            "version_conflict_engine_exception",
            {"error": "version conflict"},
        )
        _write_event(pending_event)


@pytest.mark.django_db
def test_abandoned_event_at_retry_limit_becomes_failed(
    pending_event: OutboxEvent,
) -> None:
    pending_event.status = OutboxEvent.Status.PROCESSING
    pending_event.attempts = MAX_ATTEMPTS
    pending_event.available_at = timezone.now() - timedelta(hours=1)
    pending_event.save(update_fields=["status", "attempts", "available_at"])

    assert claim_events(batch_size=1) == []

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.FAILED
