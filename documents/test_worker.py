"""Tests for the OpenSearch outbox worker."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from opensearchpy import ConflictError

from documents.models import Collection, OutboxEvent
from documents.services import create_document
from documents.worker import (
    MAX_ATTEMPTS,
    _write_event,
    claim_events,
    process_batch,
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


def prepare_claim(event: OutboxEvent) -> tuple[OutboxEvent, object]:
    """Prepare an event with a live claim for direct processing tests."""
    token = uuid4()
    event.status = OutboxEvent.Status.PROCESSING
    event.attempts = 1
    event.claim_token = token
    event.available_at = timezone.now() + timedelta(minutes=5)
    event.save(update_fields=["status", "attempts", "claim_token", "available_at"])
    return event, token


@pytest.mark.django_db
def test_claim_events_marks_event_processing(
    pending_event: OutboxEvent,
) -> None:
    claims = claim_events(batch_size=1)

    pending_event.refresh_from_db()
    assert len(claims) == 1
    event_id, token = claims[0]
    assert event_id == pending_event.id
    assert pending_event.status == OutboxEvent.Status.PROCESSING
    assert pending_event.attempts == 1
    assert pending_event.claim_token == token


@pytest.mark.django_db
def test_claim_events_uses_new_token_when_reclaiming_expired_lease(
    pending_event: OutboxEvent,
) -> None:
    first_claims = claim_events(batch_size=1)
    first_token = first_claims[0][1]

    OutboxEvent.objects.filter(id=pending_event.id).update(
        available_at=timezone.now() - timedelta(minutes=10)
    )

    second_claims = claim_events(batch_size=1)

    pending_event.refresh_from_db()
    assert len(second_claims) == 1
    assert second_claims[0][0] == pending_event.id
    assert second_claims[0][1] != first_token
    assert pending_event.claim_token == second_claims[0][1]
    assert pending_event.attempts == 2


@pytest.mark.django_db
def test_process_event_marks_successful_write_processed(
    pending_event: OutboxEvent,
) -> None:
    pending_event, token = prepare_claim(pending_event)

    with patch("documents.worker._write_event"):
        assert process_event(pending_event.id, token) is True

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.PROCESSED
    assert pending_event.processed_at is not None
    assert pending_event.last_error == ""
    assert pending_event.claim_token is None


@pytest.mark.django_db
def test_process_event_retries_failed_write(
    pending_event: OutboxEvent,
) -> None:
    pending_event, token = prepare_claim(pending_event)

    with patch(
        "documents.worker._write_event",
        side_effect=RuntimeError("temporary OpenSearch outage"),
    ):
        assert process_event(pending_event.id, token) is False

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.PENDING
    assert "temporary OpenSearch outage" in pending_event.last_error
    assert pending_event.available_at > timezone.now()
    assert pending_event.claim_token is None


@pytest.mark.django_db
def test_process_event_fails_after_retry_limit(
    pending_event: OutboxEvent,
) -> None:
    pending_event, token = prepare_claim(pending_event)
    pending_event.attempts = MAX_ATTEMPTS
    pending_event.save(update_fields=["attempts"])

    with patch(
        "documents.worker._write_event",
        side_effect=RuntimeError("permanent failure"),
    ):
        assert process_event(pending_event.id, token) is False

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.FAILED
    assert pending_event.claim_token is None


@pytest.mark.django_db
def test_stale_claim_cannot_complete_reclaimed_event(
    pending_event: OutboxEvent,
) -> None:
    pending_event, old_token = prepare_claim(pending_event)
    new_token = uuid4()
    OutboxEvent.objects.filter(id=pending_event.id).update(
        claim_token=new_token,
        available_at=timezone.now() + timedelta(minutes=5),
    )

    with patch("documents.worker._write_event"):
        assert process_event(pending_event.id, old_token) is False

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.PROCESSING
    assert pending_event.claim_token == new_token


@pytest.mark.django_db
def test_expired_claim_cannot_complete_event(
    pending_event: OutboxEvent,
) -> None:
    pending_event, token = prepare_claim(pending_event)
    OutboxEvent.objects.filter(id=pending_event.id).update(
        available_at=timezone.now() - timedelta(seconds=1)
    )

    with patch("documents.worker._write_event") as write_event:
        assert process_event(pending_event.id, token) is False

    write_event.assert_not_called()


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
    pending_event.claim_token = uuid4()
    pending_event.available_at = timezone.now() - timedelta(hours=1)
    pending_event.save(update_fields=["status", "attempts", "claim_token", "available_at"])

    assert claim_events(batch_size=1) == []

    pending_event.refresh_from_db()
    assert pending_event.status == OutboxEvent.Status.FAILED
    assert pending_event.claim_token is None


@pytest.mark.django_db
def test_document_ingestion_flows_through_outbox_to_opensearch(
    collection: Collection,
) -> None:
    document = create_document(
        collection=collection,
        external_id="end-to-end-document",
        data={
            "title": "IndexForge Integration Test",
            "content": "Searchable integration test content.",
            "url": "https://example.com/docs",
        },
    )

    event = OutboxEvent.objects.get(
        document_id=document.id,
        event_type=OutboxEvent.EventType.UPSERT,
    )

    assert event.status == OutboxEvent.Status.PENDING

    with (
        patch("documents.worker.get_opensearch_client") as get_client,
        patch(
            "documents.worker.ensure_document_index",
            return_value="test-index",
        ),
    ):
        result = process_batch(batch_size=1)

    assert result == {
        "claimed": 1,
        "processed": 1,
        "failed_or_deferred": 0,
    }

    get_client.return_value.index.assert_called_once()
    indexed = get_client.return_value.index.call_args.kwargs

    assert indexed["index"] == "test-index"
    assert indexed["id"] == str(document.id)
    assert indexed["version"] == document.version
    assert indexed["version_type"] == "external"
    assert indexed["body"]["external_id"] == "end-to-end-document"
    assert indexed["body"]["data"]["title"] == "IndexForge Integration Test"
    assert indexed["body"]["data"]["content"] == "Searchable integration test content."

    event.refresh_from_db()
    assert event.status == OutboxEvent.Status.PROCESSED
    assert event.processed_at is not None
    assert event.claim_token is None
