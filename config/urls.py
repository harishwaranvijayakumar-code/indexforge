"""URL configuration for IndexForge."""

from django.contrib import admin
from django.urls import path

from config.views import health
from documents.views import search_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/search/", search_view, name="search"),
]
