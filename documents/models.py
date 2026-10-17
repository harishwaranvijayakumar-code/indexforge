"""Database models for document ingestion and indexing events."""

import uuid

from django.db import models
from django.utils import timezone


class Collection(models.Model):
    """A logical group of documents managed by IndexForge."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    """The authoritative source record for a searchable document."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(
        Collection,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    external_id = models.CharField(max_length=255)
    data = models.JSONField()
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "external_id"],
                name="unique_external_id_per_collection",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="document_version_at_least_one",
            ),
        ]
        indexes = [
            models.Index(
                fields=["collection", "updated_at"],
                name="doc_collection_updated_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.collection.slug}:{self.external_id}"


class OutboxEvent(models.Model):
    """Durable work item created atomically with a source document change."""

    class EventType(models.TextChoices):
        UPSERT = "upsert", "Upsert"
        DELETE = "delete", "Delete"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection_id_snapshot = models.UUIDField()
    document_id = models.UUIDField()
    document_external_id = models.CharField(max_length=255)
    document_version = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["status", "available_at", "created_at"],
                name="outbox_pending_idx",
            ),
            models.Index(
                fields=["document_id", "document_version"],
                name="outbox_document_ver_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(document_version__gte=1),
                name="outbox_version_at_least_one",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "processing", "processed", "failed"]),
                name="outbox_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.document_external_id}:v{self.document_version}"
