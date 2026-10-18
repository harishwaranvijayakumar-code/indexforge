"""Process queued website crawl jobs."""

import time

from django.core.management import BaseCommand, call_command
from django.db import transaction
from django.utils import timezone

from documents.models import CrawlJob


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
            self.stderr.write(self.style.ERROR("--poll-interval must be 1-60."))
            return

        while True:
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
    def claim_job():
        with transaction.atomic():
            job = (
                CrawlJob.objects.select_for_update(skip_locked=True)
                .filter(status=CrawlJob.Status.QUEUED)
                .order_by("created_at", "id")
                .first()
            )
            if job is None:
                return None

            job.status = CrawlJob.Status.RUNNING
            job.started_at = timezone.now()
            job.error_message = ""
            job.save(update_fields=["status", "started_at", "error_message"])
            return job
