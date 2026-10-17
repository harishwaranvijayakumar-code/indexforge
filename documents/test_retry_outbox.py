"""Tests for manual outbox recovery."""

import uuid
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from documents.models import OutboxEvent


@pytest.fixture
def failed_event(db) -> OutboxEvent:
    return OutboxEvent.objects.create(
        collection_id_snapshot=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_external_id="recovery-test-1",
        document_version=3,
        event_type=OutboxEvent.EventType.UPSERT,
        payload={"data": {"name": "Preserve this payload"}},
        status=OutboxEvent.Status.FAILED,
        attempts=5,
        last_error="OpenSearch temporarily unavailable",
    )


@pytest.mark.django_db
def test_retry_command_requeues_failed_event(
    failed_event: OutboxEvent,
) -> None:
    output = StringIO()

    call_command(
        "retry_outbox",
        event_id=str(failed_event.id),
        stdout=output,
    )

    failed_event.refresh_from_db()
    assert failed_event.status == OutboxEvent.Status.PENDING
    assert failed_event.attempts == 0
    assert failed_event.available_at is not None
    assert failed_event.document_version == 3
    assert failed_event.payload == {"data": {"name": "Preserve this payload"}}
    assert failed_event.last_error == "OpenSearch temporarily unavailable"
    assert "Requeued 1" in output.getvalue()


@pytest.mark.django_db
def test_retry_command_rejects_non_failed_event(
    failed_event: OutboxEvent,
) -> None:
    failed_event.status = OutboxEvent.Status.PROCESSED
    failed_event.save(update_fields=["status"])

    with pytest.raises(CommandError, match="not currently failed"):
        call_command("retry_outbox", event_id=str(failed_event.id))


@pytest.mark.django_db
def test_retry_command_rejects_unknown_event() -> None:
    with pytest.raises(CommandError, match="No event exists"):
        call_command("retry_outbox", event_id=str(uuid.uuid4()))


@pytest.mark.django_db
def test_retry_command_respects_limit(
    failed_event: OutboxEvent,
) -> None:
    second_event = OutboxEvent.objects.create(
        collection_id_snapshot=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_external_id="recovery-test-2",
        document_version=1,
        event_type=OutboxEvent.EventType.DELETE,
        payload={},
        status=OutboxEvent.Status.FAILED,
        attempts=5,
    )

    call_command("retry_outbox", limit=1)

    statuses = {
        event.id: event.status
        for event in OutboxEvent.objects.filter(id__in=[failed_event.id, second_event.id])
    }

    assert list(statuses.values()).count(OutboxEvent.Status.PENDING) == 1
    assert list(statuses.values()).count(OutboxEvent.Status.FAILED) == 1
