"""HTTP views for document search."""

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from documents.crawl_jobs import validate_crawl_request
from documents.models import Collection, CrawlJob
from documents.search import search_documents


def serialize_crawl_job(job):
    return {
        "id": str(job.id),
        "seed_url": job.seed_url,
        "collection_slug": job.collection_slug,
        "collection_name": job.collection_name,
        "max_pages": job.max_pages,
        "status": job.status,
        "pages_visited": job.pages_visited,
        "pages_indexed": job.pages_indexed,
        "pages_skipped": job.pages_skipped,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@staff_member_required
@require_GET
def crawl_jobs_view(request):
    jobs = CrawlJob.objects.all()[:10]
    return JsonResponse({"jobs": [serialize_crawl_job(job) for job in jobs]})


@staff_member_required
@require_POST
def create_crawl_job_view(request):
    if len(request.body) > 16_384:
        return JsonResponse({"error": "Request body is too large."}, status=413)

    try:
        payload = json.loads(request.body or b"{}")
        values = validate_crawl_request(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        active_exists = CrawlJob.objects.filter(
            status__in=[CrawlJob.Status.QUEUED, CrawlJob.Status.RUNNING]
        ).exists()

        if active_exists:
            return JsonResponse(
                {"error": "A crawl is already queued or running. Wait for it to finish."},
                status=409,
            )

        job = CrawlJob.objects.create(**values)

    return JsonResponse({"job": serialize_crawl_job(job)}, status=201)


@require_GET
def search_view(request):
    """Search indexed documents through a JSON API."""
    query = request.GET.get("q", "")
    collection_slug = request.GET.get("collection", "")

    try:
        page = int(request.GET.get("page", "1"))
        page_size = int(request.GET.get("page_size", "10"))
    except ValueError:
        return JsonResponse(
            {"error": "page and page_size must be integers."},
            status=400,
        )

    if page < 1 or page_size < 1:
        return JsonResponse(
            {"error": "page and page_size must be positive integers."},
            status=400,
        )

    collection_id = None
    if collection_slug:
        try:
            collection_id = str(Collection.objects.only("id").get(slug=collection_slug).id)
        except Collection.DoesNotExist:
            return JsonResponse(
                {"error": "Collection not found."},
                status=404,
            )

    try:
        result = search_documents(
            query=query,
            collection_id=collection_id,
            page=page,
            page_size=page_size,
        )
    except Exception:
        return JsonResponse(
            {"error": "Search is temporarily unavailable."},
            status=503,
        )

    return JsonResponse(result)
