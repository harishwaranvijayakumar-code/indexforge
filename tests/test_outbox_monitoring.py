"""Tests for outbox operational metrics."""

import uuid
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from documents.models import Collection, OutboxEvent
from documents.monitoring import get_outbox_metrics


@pytest.fixture
def collection() -> Collection:
    return Collection.objects.create(
        name="Monitoring",
        slug="monitoring-tests",
    )


def create_event(
    collection: Collection,
    *,
    status: str = OutboxEvent.Status.PENDING,
    attempts: int = 0,
) -> OutboxEvent:
    """Create an outbox event for monitoring tests."""
    return OutboxEvent.objects.create(
        collection_id_snapshot=collection.id,
        document_id=uuid.uuid4(),
        document_external_id=f"document-{uuid.uuid4().hex[:8]}",
        document_version=1,
        event_type=OutboxEvent.EventType.UPSERT,
        payload={"data": {"name": "Test document"}},
        status=status,
        attempts=attempts,
    )


@pytest.mark.django_db
def test_empty_outbox_metrics() -> None:
    metrics = get_outbox_metrics()

    assert metrics["total"] == 0
    assert metrics["pending"] == 0
    assert metrics["processing"] == 0
    assert metrics["processed"] == 0
    assert metrics["failed"] == 0
    assert metrics["exhausted_retries"] == 0
    assert metrics["oldest_pending_age_seconds"] is None
    assert metrics["status"] == "ok"


@pytest.mark.django_db
def test_metrics_count_events_and_retry_exhaustion(
    collection: Collection,
) -> None:
    create_event(collection, status=OutboxEvent.Status.PENDING)
    create_event(collection, status=OutboxEvent.Status.PROCESSING)
    create_event(collection, status=OutboxEvent.Status.PROCESSED)
    create_event(collection, status=OutboxEvent.Status.FAILED, attempts=1)
    create_event(collection, status=OutboxEvent.Status.FAILED, attempts=5)

    metrics = get_outbox_metrics()

    assert metrics["total"] == 5
    assert metrics["pending"] == 1
    assert metrics["processing"] == 1
    assert metrics["processed"] == 1
    assert metrics["failed"] == 2
    assert metrics["exhausted_retries"] == 1
    assert metrics["status"] == "degraded"


@pytest.mark.django_db
def test_metrics_report_oldest_pending_event_age(
    collection: Collection,
) -> None:
    event = create_event(collection)
    old_created_at = timezone.now() - timedelta(minutes=3)
    OutboxEvent.objects.filter(id=event.id).update(
        created_at=old_created_at,
    )

    metrics = get_outbox_metrics()

    assert metrics["oldest_pending_age_seconds"] is not None
    assert metrics["oldest_pending_age_seconds"] >= 180


@pytest.mark.django_db
def test_monitoring_endpoint_returns_metrics(client: Client) -> None:
    response = client.get("/api/monitoring/outbox/")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["status"] == "ok"


def test_monitoring_endpoint_only_accepts_get(client: Client) -> None:
    response = client.post("/api/monitoring/outbox/")

    assert response.status_code == 405
