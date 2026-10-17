"""Requeue failed outbox events for another processing attempt."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from documents.models import OutboxEvent


class Command(BaseCommand):
    """Requeue failed events without changing their document payloads."""

    help = "Requeue failed outbox events for processing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--event-id",
            type=UUID,
            default=None,
            help="UUID of one failed event to retry.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of failed events to requeue (default: 100).",
        )

    def handle(self, *args, **options):
        event_id = options["event_id"]
        limit = options["limit"]

        if limit < 1:
            raise CommandError("--limit must be at least 1.")

        if event_id is not None and limit != 100:
            raise CommandError("Do not combine --event-id with --limit.")

        with transaction.atomic():
            queryset = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
                status=OutboxEvent.Status.FAILED
            )

            if event_id is not None:
                queryset = queryset.filter(id=event_id)

            events = list(queryset.order_by("created_at", "id")[:limit])

            if event_id is not None and not events:
                exists = OutboxEvent.objects.filter(id=event_id).exists()
                if exists:
                    raise CommandError("The event exists but is not currently failed.")
                raise CommandError("No event exists with that UUID.")

            now = timezone.now()
            for event in events:
                event.status = OutboxEvent.Status.PENDING
                event.attempts = 0
                event.available_at = now
                event.save(
                    update_fields=[
                        "status",
                        "attempts",
                        "available_at",
                    ]
                )

        self.stdout.write(self.style.SUCCESS(f"Requeued {len(events)} failed outbox event(s)."))
