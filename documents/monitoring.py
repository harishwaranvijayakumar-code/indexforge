"""Read-only operational metrics for the indexing outbox."""

import os
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from documents.models import OutboxEvent

MAX_ATTEMPTS = max(1, int(os.getenv("OUTBOX_MAX_ATTEMPTS", "5")))


def get_outbox_metrics() -> dict[str, Any]:
    """Return event counts, retry exhaustion, and pending-event age."""
    counts = OutboxEvent.objects.aggregate(
        total=Count("id"),
        pending=Count(
            "id",
            filter=Q(status=OutboxEvent.Status.PENDING),
        ),
        processing=Count(
            "id",
            filter=Q(status=OutboxEvent.Status.PROCESSING),
        ),
        processed=Count(
            "id",
            filter=Q(status=OutboxEvent.Status.PROCESSED),
        ),
        failed=Count(
            "id",
            filter=Q(status=OutboxEvent.Status.FAILED),
        ),
        exhausted_retries=Count(
            "id",
            filter=Q(
                status=OutboxEvent.Status.FAILED,
                attempts__gte=MAX_ATTEMPTS,
            ),
        ),
    )

    oldest_pending = (
        OutboxEvent.objects.filter(status=OutboxEvent.Status.PENDING)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )

    oldest_pending_age_seconds = None
    if oldest_pending is not None:
        oldest_pending_age_seconds = max(
            0,
            int((timezone.now() - oldest_pending).total_seconds()),
        )

    return {
        **counts,
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "status": "degraded" if counts["failed"] else "ok",
    }
