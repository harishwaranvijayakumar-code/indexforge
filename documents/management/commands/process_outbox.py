"""Process one batch of pending outbox events."""

from django.core.management.base import BaseCommand

from documents.worker import process_batch


class Command(BaseCommand):
    """Run one batch of outbox processing."""

    help = "Process one batch of document indexing events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Maximum number of events to process.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size is None:
            result = process_batch()
        else:
            if batch_size < 1:
                raise ValueError("--batch-size must be at least 1.")
            result = process_batch(batch_size=batch_size)

        self.stdout.write(
            self.style.SUCCESS(
                "Outbox batch finished: "
                f"claimed={result['claimed']}, "
                f"processed={result['processed']}, "
                f"failed_or_deferred={result['failed_or_deferred']}"
            )
        )
