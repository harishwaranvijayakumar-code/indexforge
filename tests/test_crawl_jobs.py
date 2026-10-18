import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from documents.models import CrawlJob


@pytest.fixture
def staff_client(db):
    user = get_user_model().objects.create_user(
        username="crawl-admin",
        password="test-password",
        is_staff=True,
    )
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)
    return client


def post_job(client, payload):
    return client.post(
        "/api/crawl/jobs/create/",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_non_staff_cannot_create_crawl_job():
    response = post_job(
        Client(HTTP_HOST="localhost"),
        {"seed_url": "https://example.com/"},
    )

    assert response.status_code == 302
    assert CrawlJob.objects.count() == 0


@pytest.mark.django_db
def test_staff_can_queue_bounded_crawl(staff_client):
    response = post_job(
        staff_client,
        {
            "seed_url": "https://example.com/",
            "collection_name": "Example Site",
            "max_pages": 3,
        },
    )

    assert response.status_code == 201
    job = CrawlJob.objects.get()
    assert job.collection_slug == "example-site"
    assert job.max_pages == 3
    assert job.status == CrawlJob.Status.QUEUED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"seed_url": "file:///etc/passwd", "max_pages": 2},
        {"seed_url": "https://example.com/", "max_pages": 11},
        {"seed_url": "https://example.com/", "max_pages": True},
        {"seed_url": "https://example.com/", "max_pages": 0},
    ],
)
def test_invalid_crawl_request_is_rejected(staff_client, payload):
    response = post_job(staff_client, payload)

    assert response.status_code == 400
    assert CrawlJob.objects.count() == 0


@pytest.mark.django_db
def test_only_one_active_crawl_can_be_queued(staff_client):
    CrawlJob.objects.create(
        seed_url="https://example.com/",
        collection_slug="first",
        collection_name="First",
        max_pages=1,
    )

    response = post_job(
        staff_client,
        {"seed_url": "https://example.org/"},
    )

    assert response.status_code == 409
    assert CrawlJob.objects.count() == 1


@pytest.mark.django_db
def test_staff_can_read_crawl_job_status(staff_client):
    job = CrawlJob.objects.create(
        seed_url="https://example.com/",
        collection_slug="example",
        collection_name="Example",
        max_pages=2,
    )

    response = staff_client.get("/api/crawl/jobs/")

    assert response.status_code == 200
    assert response.json()["jobs"][0]["id"] == str(job.id)
    assert response.json()["jobs"][0]["status"] == "queued"


@pytest.mark.django_db
def test_worker_claims_job_and_invokes_crawler():
    job = CrawlJob.objects.create(
        seed_url="https://example.com/",
        collection_slug="example",
        collection_name="Example",
        max_pages=2,
    )

    with patch("documents.management.commands.process_crawl_jobs.call_command") as mocked_crawl:
        call_command("process_crawl_jobs", once=True)

    mocked_crawl.assert_called_once_with(
        "crawl_site",
        job.seed_url,
        collection=job.collection_slug,
        collection_name=job.collection_name,
        max_pages=job.max_pages,
        job_id=str(job.id),
    )

    job.refresh_from_db()
    assert job.status == CrawlJob.Status.COMPLETED
    assert job.started_at is not None
    assert job.finished_at is not None


@pytest.mark.django_db
def test_worker_marks_job_failed_when_crawler_raises():
    job = CrawlJob.objects.create(
        seed_url="https://example.com/",
        collection_slug="example",
        collection_name="Example",
        max_pages=2,
    )

    with patch(
        "documents.management.commands.process_crawl_jobs.call_command",
        side_effect=RuntimeError("Simulated crawler failure"),
    ):
        call_command("process_crawl_jobs", once=True)

    job.refresh_from_db()
    assert job.status == CrawlJob.Status.FAILED
    assert "Simulated crawler failure" in job.error_message
    assert job.finished_at is not None
