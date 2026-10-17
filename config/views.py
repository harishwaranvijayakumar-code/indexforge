"""HTTP views for the IndexForge project."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    """Return a basic application health response."""
    return JsonResponse(
        {
            "status": "ok",
            "service": "indexforge",
        }
    )
