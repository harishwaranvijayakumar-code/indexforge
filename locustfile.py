"""Bounded Locust workload for IndexForge read endpoints."""

from locust import HttpUser, between, task


class IndexForgeUser(HttpUser):
    """Simulate a user checking health and searching documents."""

    wait_time = between(1, 2)

    @task(8)
    def search_documents(self):
        with self.client.get(
            "/api/search/",
            params={"q": "", "page": 1, "page_size": 10},
            name="/api/search/",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Search returned HTTP {response.status_code}")
                return

            try:
                payload = response.json()
                if not isinstance(payload.get("results"), list):
                    response.failure("Search response has no results list")
            except (ValueError, AttributeError):
                response.failure("Search response was not valid JSON")

    @task(2)
    def health_check(self):
        with self.client.get(
            "/health/",
            name="/health/",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Health returned HTTP {response.status_code}")
