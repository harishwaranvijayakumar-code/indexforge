"""Coordinate source writes with the final index rebuild cutover."""

from django.db import connection

# A stable application-specific PostgreSQL advisory lock key.
REBUILD_LOCK_KEY = 731942681


def acquire_document_write_lock() -> None:
    """Acquire the transaction-scoped lock used by source writes and rebuilds."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [REBUILD_LOCK_KEY],
        )
