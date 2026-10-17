"""URL configuration for IndexForge."""

from django.contrib import admin
from django.urls import path

from config.views import dashboard, health, outbox_monitoring, readiness
from documents.views import search_view

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("ready/", readiness, name="readiness"),
    path("api/search/", search_view, name="search"),
    path(
        "api/monitoring/outbox/",
        outbox_monitoring,
        name="outbox-monitoring",
    ),
]
