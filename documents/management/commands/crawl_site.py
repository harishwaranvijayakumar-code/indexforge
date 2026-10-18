"""Crawl a small, permitted set of public web pages into IndexForge."""

import ipaddress
import socket
import time
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documents.crawler_network import create_safe_client
from documents.models import Collection, CrawlJob, Document
from documents.services import create_document, update_document

USER_AGENT = "IndexForgeBot/0.1 (+https://github.com/harishwaranvijayakumar-code/indexforge)"
MAX_PAGES_LIMIT = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10.0


class RequestPacer:
    """Enforce a minimum delay between completed outbound HTTP requests."""

    def __init__(self, interval: float = REQUEST_DELAY_SECONDS):
        if interval < 0:
            raise ValueError("Request interval cannot be negative.")

        self.interval = interval
        self.last_request: float | None = None

    def wait(self) -> None:
        """Wait until the next outbound HTTP request is permitted."""
        if self.last_request is None:
            return

        elapsed = time.monotonic() - self.last_request
        delay = self.interval - elapsed

        if delay > 0:
            time.sleep(delay)

    def record(self) -> None:
        """Record when an outbound HTTP request has finished."""
        self.last_request = time.monotonic()


def normalize_url(url: str) -> str:
    """Normalize a URL and reject unsupported URL forms."""
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are allowed.")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must have a hostname and no embedded credentials.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port.") from exc

    scheme = parsed.scheme.lower()
    expected_port = 80 if scheme == "http" else 443

    if port is not None and port != expected_port:
        raise ValueError("Only the standard port for the URL scheme is allowed.")

    hostname = parsed.hostname.lower().rstrip(".")

    if not hostname or hostname == "localhost" or "." not in hostname:
        raise ValueError("A public internet hostname is required.")

    try:
        ip_address = ipaddress.ip_address(hostname)
    except ValueError:
        ip_address = None

    if ip_address is not None:
        if not ip_address.is_global:
            raise ValueError("Private, local, and non-public IP destinations are blocked.")
        raise ValueError("IP-literal URLs are not supported; use a public hostname.")

    cleaned = parsed._replace(
        scheme=scheme,
        netloc=hostname,
        path=parsed.path or "/",
        fragment="",
    )
    return urldefrag(urlunparse(cleaned))[0]


def validate_public_host(url: str) -> None:
    """Reject hostnames that resolve to non-public IP addresses."""
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        raise ValueError("URL has no hostname.")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Hostname could not be resolved.") from exc

    if not addresses:
        raise ValueError("Hostname did not resolve to an address.")

    for address in {item[4][0] for item in addresses}:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, local, and non-public IP destinations are blocked.")


def fetch_limited(
    client: httpx.Client,
    url: str,
    pacer: RequestPacer | None = None,
) -> tuple[httpx.Response, bytes]:
    """Fetch an HTML page without following redirects or exceeding size limits."""
    request_pacer = pacer or RequestPacer()
    request_pacer.wait()

    try:
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect response did not provide a destination.")

                destination = normalize_url(urljoin(url, location))
                validate_public_host(destination)
                raise ValueError(f"Redirect encountered; restart crawl at {destination}")

            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                raise ValueError("Response is not HTML.")

            declared_length = response.headers.get("content-length")
            if declared_length:
                try:
                    content_length = int(declared_length)
                except ValueError as exc:
                    raise ValueError("Invalid Content-Length header.") from exc

                if content_length < 0:
                    raise ValueError("Invalid Content-Length header.")
                if content_length > MAX_RESPONSE_BYTES:
                    raise ValueError("Page exceeds the 2 MB response limit.")

            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("Page exceeds the 2 MB response limit.")

            return response, bytes(body)
    finally:
        request_pacer.record()


def get_robot_parser(
    client: httpx.Client,
    start_url: str,
    pacer: RequestPacer | None = None,
) -> RobotFileParser:
    """Fetch robots.txt, failing closed when its rules cannot be verified."""
    parsed = urlparse(start_url)
    robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    validate_public_host(robots_url)

    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse([])

    request_pacer = pacer or RequestPacer()
    request_pacer.wait()

    try:
        with client.stream(
            "GET",
            robots_url,
            follow_redirects=False,
        ) as response:
            if response.status_code == 404:
                parser.parse([])
                return parser

            if response.status_code != 200:
                parser.parse(["User-agent: *", "Disallow: /"])
                return parser

            content_type = response.headers.get("content-type", "").lower()
            if content_type and not ("text/plain" in content_type or "text/html" in content_type):
                parser.parse(["User-agent: *", "Disallow: /"])
                return parser

            declared_length = response.headers.get("content-length")
            if declared_length:
                try:
                    content_length = int(declared_length)
                except ValueError:
                    parser.parse(["User-agent: *", "Disallow: /"])
                    return parser

                if content_length < 0 or content_length > MAX_ROBOTS_BYTES:
                    parser.parse(["User-agent: *", "Disallow: /"])
                    return parser

            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_ROBOTS_BYTES:
                    parser.parse(["User-agent: *", "Disallow: /"])
                    return parser

            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            return parser

    except (httpx.HTTPError, ValueError, OSError):
        parser.parse(["User-agent: *", "Disallow: /"])
        return parser
    finally:
        request_pacer.record()


class Command(BaseCommand):
    """Crawl a bounded number of same-host pages into a collection."""

    help = "Crawl permitted public HTML pages into IndexForge."

    def add_arguments(self, parser):
        parser.add_argument("url", help="Starting public HTTP/HTTPS URL")
        parser.add_argument("--collection", default="web-search")
        parser.add_argument("--collection-name", default="Web Search")
        parser.add_argument("--max-pages", type=int, default=5)
        parser.add_argument("--job-id", default=None)

    def handle(self, *args, **options):
        try:
            start_url = normalize_url(options["url"])
            validate_public_host(start_url)
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        max_pages = options["max_pages"]
        if not 1 <= max_pages <= MAX_PAGES_LIMIT:
            raise CommandError("--max-pages must be between 1 and 10.")

        job = None
        if options.get("job_id"):
            try:
                job = CrawlJob.objects.get(pk=options["job_id"])
            except (CrawlJob.DoesNotExist, ValueError) as exc:
                raise CommandError("Crawl job was not found.") from exc

            if job.status != CrawlJob.Status.RUNNING:
                raise CommandError("Crawl job is not in the running state.")

            if (
                job.seed_url != start_url
                or job.max_pages != max_pages
                or job.collection_slug != options["collection"]
            ):
                raise CommandError("Crawl arguments do not match the queued job.")

        host = urlparse(start_url).hostname
        collection, _ = Collection.objects.get_or_create(
            slug=options["collection"],
            defaults={"name": options["collection_name"]},
        )

        client = create_safe_client(user_agent=USER_AGENT)
        pacer = RequestPacer()

        indexed = 0
        skipped = 0
        visited = set()

        def save_progress(completed=False):
            if job is None:
                return

            updates = {
                "pages_visited": len(visited),
                "pages_indexed": indexed,
                "pages_skipped": skipped,
                "heartbeat_at": timezone.now(),
            }

            if completed:
                updates["status"] = CrawlJob.Status.COMPLETED
                updates["finished_at"] = timezone.now()

            CrawlJob.objects.filter(
                pk=job.pk,
                status=CrawlJob.Status.RUNNING,
            ).update(**updates)

        try:
            robots = get_robot_parser(client, start_url, pacer=pacer)
            queue = deque([start_url])

            while queue and len(visited) < max_pages:
                url = queue.popleft()
                if url in visited:
                    continue

                visited.add(url)
                save_progress()

                if not robots.can_fetch(USER_AGENT, url):
                    self.stdout.write(f"Blocked by robots.txt: {url}")
                    skipped += 1
                    save_progress()
                    continue

                try:
                    validate_public_host(url)
                    response, body = fetch_limited(client, url, pacer=pacer)
                except (ValueError, httpx.HTTPError, OSError) as exc:
                    self.stderr.write(f"Skipped {url}: {exc}")
                    skipped += 1
                    save_progress()
                    continue

                if urlparse(str(response.url)).hostname != host:
                    self.stderr.write(f"Skipped cross-host destination: {response.url}")
                    skipped += 1
                    save_progress()
                    continue

                soup = BeautifulSoup(body, "html.parser")
                for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
                    tag.decompose()

                title = soup.title.get_text(" ", strip=True) if soup.title else url
                content = " ".join(soup.stripped_strings)[:100_000]

                if not content:
                    skipped += 1
                    save_progress()
                    continue

                data = {
                    "name": title[:500],
                    "title": title[:500],
                    "url": url,
                    "content": content,
                    "category": "web-page",
                    "source_host": host,
                }

                try:
                    existing = Document.objects.filter(
                        collection=collection,
                        external_id=url,
                    ).first()

                    if existing:
                        update_document(
                            collection=collection,
                            external_id=url,
                            data=data,
                        )
                    else:
                        create_document(
                            collection=collection,
                            external_id=url,
                            data=data,
                        )

                    indexed += 1
                    save_progress()

                except Exception as exc:
                    self.stderr.write(f"Could not save {url}: {exc}")
                    skipped += 1
                    save_progress()
                    continue

                for link in soup.find_all("a", href=True):
                    candidate = urljoin(url, link["href"])
                    try:
                        candidate = normalize_url(candidate)
                    except ValueError:
                        continue

                    if urlparse(candidate).hostname != host:
                        continue

                    if candidate not in visited and candidate not in queue:
                        queue.append(candidate)

                self.stdout.write(f"Indexed: {url} — {title[:100]}")

        finally:
            client.close()

        save_progress(completed=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Crawl complete. Indexed or updated: {indexed}; "
                f"skipped: {skipped}; visited: {len(visited)}; "
                f"collection: {collection.slug}"
            )
        )
