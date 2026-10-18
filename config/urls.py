"""URL configuration for IndexForge."""

from django.contrib import admin
from django.urls import path

from config.views import dashboard, health, outbox_monitoring, readiness
from documents.views import crawl_jobs_view, create_crawl_job_view, search_view

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
    path("api/crawl/jobs/", crawl_jobs_view, name="crawl-jobs"),
    path("api/crawl/jobs/create/", create_crawl_job_view, name="create-crawl-job"),
]