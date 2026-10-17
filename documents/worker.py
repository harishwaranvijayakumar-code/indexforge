"""Process durable outbox events and synchronize OpenSearch."""

import os
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone
from opensearchpy import ConflictError

from documents.index_manager import ensure_document_index
from documents.models import OutboxEvent
from documents.search_client import get_opensearch_client

BATCH_SIZE = max(1, int(os.getenv("OUTBOX_BATCH_SIZE", "50")))
MAX_ATTEMPTS = max(1, int(os.getenv("OUTBOX_MAX_ATTEMPTS", "5")))
RETRY_BASE_SECONDS = max(1, int(os.getenv("OUTBOX_RETRY_BASE_SECONDS", "2")))
PROCESSING_TIMEOUT_SECONDS = max(
    30,
    int(os.getenv("OUTBOX_PROCESSING_TIMEOUT_SECONDS", "300")),
)


def claim_events(
    batch_size: int = BATCH_SIZE,
) -> list[tuple[UUID, UUID]]:
    """Claim eligible events and return event IDs with their claim tokens."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    now = timezone.now()
    abandoned_before = now - timedelta(seconds=PROCESSING_TIMEOUT_SECONDS)
    claimed: list[OutboxEvent] = []

    with transaction.atomic():
        exhausted = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                status=OutboxEvent.Status.PROCESSING,
                available_at__lte=abandoned_before,
                attempts__gte=MAX_ATTEMPTS,
            )
            .order_by("created_at", "id")
        )
        for event in exhausted:
            event.status = OutboxEvent.Status.FAILED
            event.claim_token = None
            event.last_error = "Processing lease expired after the retry limit."
            event.save(update_fields=["status", "claim_token", "last_error"])

        pending = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                status=OutboxEvent.Status.PENDING,
                available_at__lte=now,
                attempts__lt=MAX_ATTEMPTS,
            )
            .order_by("created_at", "id")[:batch_size]
        )
        claimed.extend(pending)

        remaining = batch_size - len(claimed)
        if remaining > 0:
            abandoned = list(
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(
                    status=OutboxEvent.Status.PROCESSING,
                    available_at__lte=abandoned_before,
                    attempts__lt=MAX_ATTEMPTS,
                )
                .order_by("created_at", "id")[:remaining]
            )
            claimed.extend(abandoned)

        claims: list[tuple[UUID, UUID]] = []
        for event in claimed:
            token = uuid4()
            event.status = OutboxEvent.Status.PROCESSING
            event.attempts += 1
            event.claim_token = token
            event.available_at = now + timedelta(seconds=PROCESSING_TIMEOUT_SECONDS)
            event.save(
                update_fields=[
                    "status",
                    "attempts",
                    "claim_token",
                    "available_at",
                ]
            )
            claims.append((event.id, token))

    return claims


def _write_event(event: OutboxEvent) -> None:
    """Apply an event with version protection in OpenSearch."""
    client = get_opensearch_client()
    index_name = ensure_document_index()
    payload: dict[str, Any] = event.payload

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
        return


def _owns_live_claim(event_id: UUID, claim_token: UUID) -> bool:
    """Check whether the claim token still owns an unexpired lease."""
    return OutboxEvent.objects.filter(
        id=event_id,
        status=OutboxEvent.Status.PROCESSING,
        claim_token=claim_token,
        available_at__gt=timezone.now(),
    ).exists()


def process_event(event_id: UUID, claim_token: UUID) -> bool:
    """Process a claimed event only while its lease remains valid."""
    try:
        event = OutboxEvent.objects.get(
            id=event_id,
            status=OutboxEvent.Status.PROCESSING,
            claim_token=claim_token,
            available_at__gt=timezone.now(),
        )
    except OutboxEvent.DoesNotExist:
        return False

    try:
        _write_event(event)
    except Exception as exc:
        now = timezone.now()
        retry_delay = RETRY_BASE_SECONDS * (2 ** (event.attempts - 1))

        with transaction.atomic():
            try:
                current = OutboxEvent.objects.select_for_update().get(
                    id=event_id,
                    status=OutboxEvent.Status.PROCESSING,
                    claim_token=claim_token,
                    available_at__gt=now,
                )
            except OutboxEvent.DoesNotExist:
                return False

            current.last_error = str(exc)[:4000]
            current.available_at = now + timedelta(seconds=retry_delay)
            current.status = (
                OutboxEvent.Status.FAILED
                if current.attempts >= MAX_ATTEMPTS
                else OutboxEvent.Status.PENDING
            )
            current.claim_token = None
            current.save(
                update_fields=[
                    "status",
                    "available_at",
                    "last_error",
                    "claim_token",
                ]
            )

        return False

    with transaction.atomic():
        try:
            current = OutboxEvent.objects.select_for_update().get(
                id=event_id,
                status=OutboxEvent.Status.PROCESSING,
                claim_token=claim_token,
                available_at__gt=timezone.now(),
            )
        except OutboxEvent.DoesNotExist:
            return False

        current.status = OutboxEvent.Status.PROCESSED
        current.processed_at = timezone.now()
        current.last_error = ""
        current.claim_token = None
        current.save(
            update_fields=[
                "status",
                "processed_at",
                "last_error",
                "claim_token",
            ]
        )

    return True


def process_batch(batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """Claim and process one batch of outbox events."""
    claims = claim_events(batch_size=batch_size)
    succeeded = sum(process_event(event_id, token) for event_id, token in claims)

    return {
        "claimed": len(claims),
        "processed": succeeded,
        "failed_or_deferred": len(claims) - succeeded,
    }
