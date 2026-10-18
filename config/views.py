"""HTTP views for the IndexForge service and dashboard."""

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from documents.monitoring import get_outbox_metrics
from documents.search_client import get_opensearch_client


def dashboard(request):
    """Render the IndexForge operations dashboard."""
    return render(
        request,
        "index.html",
        {"can_crawl": (request.user.is_authenticated and request.user.is_staff)},
    )


@require_GET
def health(request):
    """Return a basic application health response."""
    return JsonResponse(
        {
            "status": "ok",
            "service": "indexforge",
        }
    )


@require_GET
def readiness(request):
    """Check whether PostgreSQL and OpenSearch are ready."""
    checks = {
        "postgres": False,
        "opensearch": False,
    }

    try:
        connection.ensure_connection()
        checks["postgres"] = True
    except Exception:
        pass

    try:
        response = get_opensearch_client().cluster.health(request_timeout=3)
        checks["opensearch"] = response.get("status") in {"green", "yellow"}
    except Exception:
        pass

    is_ready = all(checks.values())

    return JsonResponse(
        {
            "status": "ok" if is_ready else "unavailable",
            "service": "indexforge",
            "checks": checks,
        },
        status=200 if is_ready else 503,
    )


@require_GET
def outbox_monitoring(request):
    """Return read-only outbox operational metrics."""
    return JsonResponse(get_outbox_metrics())
