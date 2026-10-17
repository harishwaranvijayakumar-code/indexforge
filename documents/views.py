"""HTTP views for document search."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from documents.models import Collection
from documents.search import search_documents


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
