"""Tests for application readiness."""

from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_readiness_returns_200_when_dependencies_are_ready(
    client: Client,
) -> None:
    with (
        patch("config.views.connection.ensure_connection"),
        patch("config.views.get_opensearch_client") as get_client,
    ):
        get_client.return_value.cluster.health.return_value = {
            "status": "green",
        }

        response = client.get("/ready/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {
        "postgres": True,
        "opensearch": True,
    }


@pytest.mark.django_db
def test_readiness_returns_503_when_postgres_is_unavailable(
    client: Client,
) -> None:
    with (
        patch(
            "config.views.connection.ensure_connection",
            side_effect=RuntimeError("database unavailable"),
        ),
        patch("config.views.get_opensearch_client") as get_client,
    ):
        get_client.return_value.cluster.health.return_value = {
            "status": "green",
        }

        response = client.get("/ready/")

    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] is False
    assert response.json()["checks"]["opensearch"] is True


@pytest.mark.django_db
def test_readiness_returns_503_when_opensearch_is_unavailable(
    client: Client,
) -> None:
    with (
        patch("config.views.connection.ensure_connection"),
        patch("config.views.get_opensearch_client") as get_client,
    ):
        get_client.return_value.cluster.health.side_effect = RuntimeError("OpenSearch unavailable")

        response = client.get("/ready/")

    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] is True
    assert response.json()["checks"]["opensearch"] is False


def test_health_endpoint_remains_available(client: Client) -> None:
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "indexforge",
    }
