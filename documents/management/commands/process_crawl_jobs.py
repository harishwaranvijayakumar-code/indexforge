"""Process queued website crawl jobs and detect stale workers."""

import time
from datetime import timedelta

from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from documents.models import CrawlJob

STALE_JOB_MINUTES = 15


class Command(BaseCommand):
    help = "Process queued IndexForge crawl jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one job, then exit.",
        )
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=2,
            help="Seconds between checks when waiting for jobs (1-60).",
        )

    def handle(self, *args, **options):
        interval = options["poll_interval"]

        if not 1 <= interval <= 60:
            raise CommandError("--poll-interval must be between 1 and 60.")

        while True:
            self.fail_stale_jobs()
            job = self.claim_job()

            if job is None:
                if options["once"]:
                    self.stdout.write("No queued crawl jobs.")
                    return

                time.sleep(interval)
                continue

            self.stdout.write(f"Processing crawl job {job.id}")

            try:
                call_command(
                    "crawl_site",
                    job.seed_url,
                    collection=job.collection_slug,
                    collection_name=job.collection_name,
                    max_pages=job.max_pages,
                    job_id=str(job.id),
                )

                job.refresh_from_db()

                if job.status == CrawlJob.Status.RUNNING:
                    job.status = CrawlJob.Status.COMPLETED
                    job.finished_at = timezone.now()
                    job.save(update_fields=["status", "finished_at"])

            except Exception as exc:
                CrawlJob.objects.filter(
                    pk=job.pk,
                    status=CrawlJob.Status.RUNNING,
                ).update(
                    status=CrawlJob.Status.FAILED,
                    error_message=str(exc)[:4000],
                    finished_at=timezone.now(),
                )

                self.stderr.write(self.style.ERROR(f"Crawl job {job.id} failed: {exc}"))

            if options["once"]:
                return

    @staticmethod
    def fail_stale_jobs():
        """Mark inactive running jobs as failed instead of retrying them."""
        cutoff = timezone.now() - timedelta(minutes=STALE_JOB_MINUTES)

        stale_jobs = CrawlJob.objects.filter(
            status=CrawlJob.Status.RUNNING,
        ).filter(Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True, started_at__lt=cutoff))

        return stale_jobs.update(
            status=CrawlJob.Status.FAILED,
            error_message=(
                "Crawl job was marked failed because no heartbeat "
                f"was recorded for {STALE_JOB_MINUTES} minutes. "
                "Review its progress before starting a new crawl."
            ),
            finished_at=timezone.now(),
        )

    @staticmethod
    def claim_job():
        """Atomically claim the oldest queued crawl job."""
        with transaction.atomic():
            job = (
                CrawlJob.objects.select_for_update(skip_locked=True)
                .filter(status=CrawlJob.Status.QUEUED)
                .order_by("created_at", "id")
                .first()
            )

            if job is None:
                return None

            now = timezone.now()
            job.status = CrawlJob.Status.RUNNING
            job.started_at = now
            job.heartbeat_at = now
            job.finished_at = None
            job.error_message = ""

            job.save(
                update_fields=[
                    "status",
                    "started_at",
                    "heartbeat_at",
                    "finished_at",
                    "error_message",
                ]
            )

            return job
