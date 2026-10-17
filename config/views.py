"""HTTP views for the IndexForge project."""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from documents.search_client import get_opensearch_client


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
        response = get_opensearch_client().cluster.health(
            request_timeout=3,
        )
        checks["opensearch"] = response.get("status") in {
            "green",
            "yellow",
        }
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
