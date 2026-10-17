"""OpenSearch client configuration."""

import os
from functools import lru_cache
from urllib.parse import urlparse

from opensearchpy import OpenSearch


@lru_cache(maxsize=1)
def get_opensearch_client() -> OpenSearch:
    """Return a reusable OpenSearch client."""
    url = urlparse(os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200"))

    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError("OPENSEARCH_URL must be a valid HTTP or HTTPS URL.")

    return OpenSearch(
        hosts=[
            {
                "host": url.hostname,
                "port": url.port or (443 if url.scheme == "https" else 80),
                "scheme": url.scheme,
            }
        ],
        use_ssl=url.scheme == "https",
        verify_certs=url.scheme == "https",
        timeout=5,
        max_retries=2,
        retry_on_timeout=True,
    )
