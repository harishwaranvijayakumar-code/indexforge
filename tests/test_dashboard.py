
import pytest
from django.test import Client


@pytest.fixture
def dashboard_client() -> Client:
    return Client(HTTP_HOST="localhost")


@pytest.mark.django_db
def test_dashboard_renders(dashboard_client: Client) -> None:
    response = dashboard_client.get("/")

    assert response.status_code == 200
    assert b"IndexForge" in response.content
    assert b"Your data." in response.content
    assert b"In focus." in response.content
    assert b"search-form" in response.content
    assert b"search-query" in response.content


@pytest.mark.django_db
def test_dashboard_includes_static_assets(dashboard_client: Client) -> None:
    response = dashboard_client.get("/")
    html = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "dashboard.css" in html or "/static/" in html
    assert "dashboard.js" in html or "/static/" in html