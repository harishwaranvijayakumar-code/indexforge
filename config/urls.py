"""URL configuration for IndexForge."""

from django.contrib import admin
from django.urls import path

from config.views import health, readiness
from documents.views import search_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("ready/", readiness, name="readiness"),
    path("api/search/", search_view, name="search"),
]
