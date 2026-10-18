# IndexForge — Reliable Search Index Management

**Keep search reliable while the data changes.**

[Try IndexForge](https://indexforge-awp2.onrender.com)

IndexForge is a search-index management service designed to keep searchable documents synchronized with their PostgreSQL source records while indexing operations, background workers, and index replacements encounter failures.

The project investigates the engineering problems behind reliable search infrastructure: incremental indexing, transactional event delivery, retry handling, operational visibility, safe index rebuilding, and rollback.

IndexForge is a working application, not a simulator. It provides a dashboard, document search, indexing operations, monitoring, and a controlled website-crawling workflow.

---

## Table of Contents

- [Project Thesis](#project-thesis)
- [The Engineering Problem](#the-engineering-problem)
- [What IndexForge Does](#what-indexforge-does)
- [Core Design Principles](#core-design-principles)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Core Data Model](#core-data-model)
- [Document Ingestion and Indexing](#document-ingestion-and-indexing)
- [Transactional Outbox](#transactional-outbox)
- [Retries and Recovery](#retries-and-recovery)
- [Search Index Lifecycle](#search-index-lifecycle)
- [Website Crawling](#website-crawling)
- [Operational Dashboard](#operational-dashboard)
- [HTTP Endpoints](#http-endpoints)
- [Local Development](#local-development)
- [Configuration](#configuration)
- [Running Background Workers](#running-background-workers)
- [Testing and CI](#testing-and-ci)
- [Experiments and Performance](#experiments-and-performance)
- [Production Deployment](#production-deployment)
- [Security Considerations](#security-considerations)
- [Current Limitations](#current-limitations)
- [Engineering Roadmap](#engineering-roadmap)
- [Project Status](#project-status)
- [Key Takeaway](#key-takeaway)

---

# Project Thesis

Search systems are expected to return useful, up-to-date results even while the underlying data changes.

A document may be created, updated, or deleted in PostgreSQL. The corresponding OpenSearch operation may fail. A worker may stop after claiming an event. A retry may process an event more than once. An index rebuild may encounter invalid data or fail validation.

These failures create a fundamental question:

> How can a search system keep its source data authoritative, make indexing recoverable, and replace an index without exposing users to an incomplete search view?

A straightforward implementation might write to a database and immediately send a request to a search engine.

That approach introduces a consistency gap:

```text
Application
    |
    v
PostgreSQL write succeeds
    |
    v
OpenSearch request fails
    |
    v
Source data and search index disagree
```

The source record exists, but the search index may not contain the latest version.

IndexForge addresses this class of problem through durable indexing events, retryable processing, operational monitoring, and controlled index lifecycle operations.

The engineering approach is investigation-driven:

```text
Real engineering problem
          |
          v
Understand the failure mode
          |
          v
Define a correctness invariant
          |
          v
Design a mechanism
          |
          v
Implement the mechanism
          |
          v
Introduce or reproduce failure
          |
          v
Measure the result
          |
          v
Validate the invariant
          |
          v
Document the trade-offs
```

The goal is not simply to make search work on the happy path. It is to make the behavior of the system understandable and recoverable when individual components fail.

---

# The Engineering Problem

## 1. Keeping Search Fresh

PostgreSQL and OpenSearch serve different purposes.

PostgreSQL stores authoritative application data. OpenSearch maintains an index optimized for search.

When a source document changes, its search representation must eventually reflect that change.

The two systems do not share one ordinary database transaction.

```text
Document update
      |
      v
PostgreSQL commit
      |
      v
Indexing event
      |
      v
OpenSearch update
      |
      v
Search results reflect the change
```

The indexing step can fail even after the database transaction succeeds.

IndexForge separates source-data persistence from search-index synchronization so that failed indexing work can be retried and observed.

## 2. The Dual-Write Problem

Consider an application that performs two independent operations:

1. Save a document in PostgreSQL.
2. Send an indexing request to OpenSearch.

If the database write succeeds but the indexing request fails, the systems disagree.

Reversing the order does not solve the problem. An OpenSearch operation could succeed while the database transaction later fails.

The core issue is that these operations are not one atomic transaction.

IndexForge uses a transactional outbox to make the intent to index part of the source database transaction.

## 3. Duplicate Event Processing

A worker may process an event and fail before recording its completion. The event can then be processed again.

A reliable indexing system must tolerate retries and repeated delivery without creating duplicate logical documents or losing updates.

The relevant invariant is:

```text
Repeated processing of an event
             |
             v
Same logical document state
```

This requires stable document identifiers, appropriate database constraints, and predictable indexing operations.

## 4. Worker Failures

Background workers can fail because of process termination, network errors, service interruptions, or unexpected application errors.

A worker may also claim an event but fail before completing it.

IndexForge uses claim-token protection and processing-timeout configuration to reduce the risk of stale workers incorrectly completing work that has been reclaimed.

## 5. Index Rebuilding

Search indexes sometimes need to be rebuilt because of mapping changes, index configuration changes, or recovery requirements.

Replacing the active index too early can expose users to an incomplete search view.

The lifecycle needs to separate building a candidate index from making that index active.

```text
Active index remains available
              |
              v
Build replacement index
              |
              v
Populate documents
              |
              v
Validate replacement
              |
              v
Switch active alias
              |
              v
New index serves search traffic
```

If the replacement cannot be validated, the existing index should remain active. The rollback workflow provides a way to restore a previous index target when necessary.

## 6. Operating the System

A search API alone does not explain whether the indexing pipeline is healthy.

Operators need to understand:

- How many events are pending.
- Whether processing is succeeding.
- Whether events are failing or being deferred.
- Whether crawl jobs are progressing.
- Whether PostgreSQL and OpenSearch are reachable.
- Whether a replacement index is active.

IndexForge exposes operational information through its dashboard and monitoring endpoints.

---

# What IndexForge Does

IndexForge provides the following application capabilities.

| Capability | Purpose |
|---|---|
| Document and collection management | Maintain searchable source records |
| Document search | Retrieve indexed documents through OpenSearch |
| Transactional outbox | Persist indexing intent alongside source-data changes |
| Batch indexing worker | Process pending outbox events |
| Retry and recovery operations | Recover eligible failed or deferred indexing work |
| Outbox monitoring | Expose operational processing metrics |
| Index rebuilding | Construct a replacement search index |
| Index rollback | Restore a previous index target when needed |
| Website crawling | Discover permitted public web pages and index their content |
| Crawl-job dashboard | Submit and inspect crawl jobs |
| Health endpoint | Check basic application responsiveness |
| Readiness endpoint | Check PostgreSQL and OpenSearch connectivity |
| Automated tests and CI | Validate application behavior and code quality |

IndexForge is not a general-purpose web search engine that automatically searches the entire internet. Its search results come from documents that have been ingested or crawled into its collections.

Entering a website URL into the search field does not, by itself, cause the entire website to be crawled. Website discovery is a separate operation.

---

# Core Design Principles

## PostgreSQL Is the Source of Truth

The source document is authoritative.

OpenSearch is a derived representation of that document, optimized for retrieval.

If the index becomes inconsistent, the system should be able to use the source records and indexing workflow to restore the search representation.

## Source Writes and Indexing Intent Must Be Atomic

A successful source-data transaction should not silently lose the intention to update the index.

The transactional outbox stores that intention in PostgreSQL within the same transaction as the relevant source-data change.

## Search Visibility Is Eventually Consistent

A committed source update does not necessarily become searchable immediately.

The time between the database commit and successful index processing is the indexing lag.

This distinction is intentional. IndexForge favors durable indexing intent and recoverability over pretending that PostgreSQL and OpenSearch share a distributed atomic transaction.

## Retried Work Must Be Safe

An event may be delivered more than once.

Processing must be designed around stable document identity and repeatable operations rather than assuming every event is delivered exactly once.

## Rebuilds Must Not Prematurely Replace the Active Index

A candidate index should be prepared and validated before the active alias is switched.

The previous index remains the recovery option when a replacement fails validation or needs to be rolled back.

## Operational Claims Must Be Measurable

Performance and reliability claims should be supported by repeatable tests, observed metrics, or documented experiments.

A successful request is not evidence of high availability, and a successful build is not evidence of correct production configuration.

---

# Architecture

IndexForge uses Django as the application layer, PostgreSQL as the source-data and event store, and OpenSearch as the search engine.

```text
                       Browser
                          |
                          v
                +--------------------+
                | Django Dashboard   |
                | and HTTP API       |
                +---------+----------+
                          |
             +------------+------------+
             |                         |
             v                         v
    +----------------+       +------------------+
    | PostgreSQL     |       | Search API       |
    |                |       |                  |
    | Collections    |       | OpenSearch       |
    | Documents      |       | queries          |
    | Outbox events  |       +--------+---------+
    | Crawl jobs     |                |
    +-------+--------+                v
            |                  +-------------+
            |                  | OpenSearch  |
            v                  | Index/Alias |
    +----------------+         +-------------+
    | Outbox Worker  |
    +--------+-------+
             |
             v
       Index documents

    +----------------+
    | Crawl Worker   |
    +--------+-------+
             |
             v
    Permitted public pages
             |
             v
    PostgreSQL documents
             |
             v
       Indexing pipeline
```

The outbox and crawl workers are implemented as Django management commands. Their execution schedule depends on the deployment environment.

## Request and Indexing Flow

A typical document update follows this sequence:

```text
Client request
      |
      v
Django application
      |
      v
PostgreSQL transaction
  |                |
  v                v
Document       Outbox event
  |                |
  +-------+--------+
          |
          v
   Transaction commits
          |
          v
   Outbox worker claims event
          |
          v
   OpenSearch indexing operation
          |
          v
   Event processing result recorded
          |
          v
   Updated document becomes searchable
```

The key design choice is that the source document and its indexing intent are persisted together.

---

# Technology Stack

## Backend

- Python 3.13
- Django 5.2
- Django ORM
- Gunicorn

## Source Database

- PostgreSQL 17
- Psycopg

## Search Engine

- OpenSearch 3.9
- `opensearch-py`

## Frontend

- Django templates
- HTML
- CSS
- JavaScript

The interface is designed as a search and operations product rather than a generic administration page.

## Static Assets

- WhiteNoise
- Django static-file collection

## Crawling

- HTTPX
- Beautiful Soup

## Development and Quality

- Docker Compose
- pytest
- pytest-django
- Ruff
- GitHub Actions

## Hosting

- Render for the Django web service
- Aiven PostgreSQL for source data
- Aiven OpenSearch for indexed search data

The hosted services are configured through environment variables rather than committed credentials.

---

# Repository Structure

The repository is organized around the Django application, the document domain, the indexing pipeline, and the dashboard.

```text
indexforge/
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── views.py
│   ├── wsgi.py
│   └── asgi.py
│
├── documents/
│   ├── management/
│   │   └── commands/
│   │       ├── crawl_site.py
│   │       ├── process_crawl_jobs.py
│   │       ├── process_outbox.py
│   │       ├── rebuild_index.py
│   │       ├── retry_outbox.py
│   │       └── rollback_index.py
│   │
│   ├── static/
│   │   └── documents/
│   │       ├── dashboard.css
│   │       └── dashboard.js
│   │
│   ├── templates/
│   ├── models.py
│   ├── views.py
│   ├── worker.py
│   ├── search_client.py
│   ├── index_manager.py
│   └── monitoring.py
│
├── templates/
│   └── index.html
│
├── tests/
│   └── test_health.py
│
├── .env.example
├── .gitignore
├── docker-compose.yml
├── manage.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

The structure above highlights the principal application areas. Additional test modules and application files are present in the repository.

### Important modules

**`documents/models.py`**

Defines the document domain and persistence models, including collections, documents, outbox events, and crawl jobs.

**`documents/worker.py`**

Implements outbox processing and its configured batch, retry, and timeout behavior.

**`documents/search_client.py`**

Creates a reusable OpenSearch client, supporting HTTP for local development and HTTPS with certificate verification for hosted endpoints. Optional basic authentication can be configured using environment variables.

**`documents/index_manager.py`**

Contains the index naming and alias configuration used by the index lifecycle.

**`documents/monitoring.py`**

Provides outbox operational metrics and retry-related configuration.

**`documents/management/commands/`**

Contains the operational commands for processing events, managing crawl jobs, rebuilding indexes, retrying eligible outbox work, and rolling back index targets.

---

# Core Data Model

IndexForge separates authoritative source data from the operational records required to maintain the search index.

## Collection

A collection groups documents into a logical search scope.

A collection provides a way to organize related content rather than treating the entire index as one undifferentiated set of records.

## Document

A document represents the source content that IndexForge stores and makes searchable.

The PostgreSQL record is authoritative. OpenSearch contains the searchable representation.

Documents may originate from application ingestion or the website-crawling workflow.

## OutboxEvent

An outbox event records indexing work associated with a source-data change.

The event allows indexing to happen independently of the original HTTP request while preserving the intent to synchronize the search representation.

The worker processes these events in batches.

Processing outcomes are observable through the outbox monitoring endpoint and dashboard.

## CrawlJob

A crawl job records a requested website-crawling operation.

The crawl worker claims queued jobs, executes the crawling command, and records completion or failure.

The job includes operational state used to track progress and identify stale work.

## Source Records and Search Documents

The conceptual relationship is:

```text
PostgreSQL
    |
    +-- Collection
    |
    +-- Document
    |
    +-- OutboxEvent
    |
    +-- CrawlJob

OpenSearch
    |
    +-- Searchable document representation
    +-- Index lifecycle and aliases
```

PostgreSQL and OpenSearch have distinct responsibilities. The search index is not the authoritative record of the application data.

---

# Document Ingestion and Indexing

IndexForge separates accepting source data from making it searchable.

This is necessary because indexing is a separate operation that can fail independently.

## Conceptual workflow

```text
Create or update document
           |
           v
Persist source record
           |
           v
Persist outbox event
           |
           v
Commit transaction
           |
           v
Worker processes event
           |
           v
Update OpenSearch
           |
           v
Search reflects the change
```

If OpenSearch is unavailable during processing, the outbox event remains available for retry or recovery according to its state and processing rules.

## Search behavior

The search API queries OpenSearch, not PostgreSQL directly.

This means:

- Documents must be indexed before they can appear in search results.
- Newly committed documents may not be immediately searchable.
- Search results depend on the active index and its current contents.
- A successful database write alone does not prove that indexing succeeded.

The dashboard and operational endpoints help distinguish source-data availability from search-index availability.

---

# Transactional Outbox

The transactional outbox addresses the problem of maintaining source data and indexing intent without attempting a distributed transaction across PostgreSQL and OpenSearch.

## The failure it prevents

Without an outbox:

```text
PostgreSQL write succeeds
          |
          v
Application process stops
          |
          v
OpenSearch update never occurs
```

If the indexing intention existed only in application memory, the process failure could lose it.

## The outbox approach

With the transactional outbox:

```text
Database transaction
       |
       +-- Write document
       |
       +-- Write outbox event
       |
       v
Transaction commits
       |
       v
Independent worker processes event
```

If the transaction rolls back, its document change and corresponding outbox event do not become committed records.

If the transaction commits, the indexing intention is durable in PostgreSQL.

## Batch processing

The `process_outbox` management command processes one batch and exits.

Its optional `--batch-size` argument controls the maximum number of events processed by that invocation.

The default batch size is configurable through `OUTBOX_BATCH_SIZE`.

Example:

```powershell
python manage.py process_outbox
```

To process a smaller batch:

```powershell
python manage.py process_outbox --batch-size 10
```

This is a one-shot batch command, not a continuously running daemon.

---

# Retries and Recovery

IndexForge treats failed indexing operations as operational work that needs visibility and recovery.

## Bounded processing

The application exposes configuration for:

- Maximum outbox processing attempts
- Retry base delay
- Outbox batch size
- Processing timeout

These settings help constrain retry behavior and prevent unbounded processing attempts.

## Processing claim protection

The worker uses claim-token protection to reduce the risk of a stale processing attempt incorrectly completing work after the event has been reclaimed.

This matters when a worker experiences delays, loses connectivity, or continues operating after another process has taken responsibility for the event.

## Manual recovery

IndexForge provides management commands for:

- Processing an outbox batch
- Retrying eligible outbox events
- Monitoring outbox state

The exact recovery action should be chosen after inspecting the event's current state and the failure that caused it.

A retry is not a substitute for diagnosing a permanent configuration problem. Repeatedly retrying an unreachable search endpoint, for example, will not restore connectivity.

## Observability

The outbox monitoring endpoint exposes operational metrics, allowing operators to inspect processing health without querying internal tables manually.

This separates the question of whether a source write succeeded from the question of whether its search-index update succeeded.

---

# Search Index Lifecycle

Index rebuilding is one of the core reliability features in IndexForge.

Rebuilding an index while users continue searching requires care. A replacement must not become the active search target before it is ready.

## Active index and alias

The default configuration uses:

```text
Index: indexforge-documents-v1
Alias: indexforge-documents
```

The index name identifies an index generation. The alias provides a stable target for search operations while the underlying index can be changed.

The configured names can be overridden through environment variables.

## Safe rebuild workflow

The lifecycle is designed around a candidate index and a controlled replacement:

```text
Existing index remains active
              |
              v
Create replacement index
              |
              v
Populate replacement
              |
              v
Validate replacement
              |
              v
Switch active alias
              |
              v
New index receives search traffic
```

This separates index construction from index activation.

## Rollback

IndexForge includes a rollback management command for restoring a previous index target.

Rollback is useful when a newly activated index has problems that were not detected during the rebuild validation.

The alias-based design helps avoid requiring application code to change its search target every time the index generation changes.

## Operational commands

The repository includes:

```text
rebuild_index
rollback_index
```

These are Django management commands. Consult their command-line help before executing them in a hosted environment:

```powershell
python manage.py help rebuild_index
python manage.py help rollback_index
```

Rebuilding and rollback should be treated as operational changes. Verify the source data, index targets, and current alias state before running them against the deployed service.

---

# Website Crawling

IndexForge includes a website-crawling workflow that discovers permitted public web pages and indexes their content.

Crawling is a separate ingestion path from direct document ingestion.

## Conceptual workflow

```text
Submit seed URL
       |
       v
Create crawl job
       |
       v
Worker claims queued job
       |
       v
Fetch permitted pages
       |
       v
Extract page content
       |
       v
Persist documents
       |
       v
Transactional outbox
       |
       v
OpenSearch indexing
       |
       v
Crawled content becomes searchable
```

## Crawling restrictions

The crawler incorporates safety controls, including:

- Restricting crawling to permitted public pages
- Same-host crawling
- Respecting `robots.txt`
- Page and response limits
- Redirects not followed automatically
- Public DNS validation and destination pinning

These controls reduce the risk of crawling private infrastructure or allowing an arbitrary URL to become an unrestricted network-access mechanism.

Crawling remains subject to the website's access rules, rate limits, and applicable terms.

## Crawl-job processing

The repository includes:

```text
crawl_site
process_crawl_jobs
```

The crawl worker can run in one-shot mode:

```powershell
python manage.py process_crawl_jobs --once
```

This invocation processes at most one queued job and then exits.

Without `--once`, the worker continues polling for jobs. That mode requires a process environment capable of keeping the command running.

The worker also detects stale running jobs and marks them failed when the required heartbeat or progress information is absent for the configured stale-job interval.

## What the crawler does not do

Submitting a seed URL does not guarantee that every page on the website will be discovered or indexed.

The crawler is constrained by its page limits, host restrictions, robots policy, response handling, and the site's actual link structure.

A URL supplied to the search box is a search query; it is not automatically a crawl request.

---

# Operational Dashboard

IndexForge includes a dashboard intended to make search operations visible.

The interface contains the following principal sections:

| Section | Purpose |
|---|---|
| Search | Search indexed documents |
| Discovery | Explore the document-search workflow |
| Crawl | Submit and inspect crawl jobs |
| Platform | Inspect service and indexing information |
| Activity | Review operational activity and processing state |

The interface uses HTML, CSS, and JavaScript, with static assets served through WhiteNoise in deployment.

The dashboard is designed around operational visibility rather than simply presenting document records in a generic table.

## Health and readiness

IndexForge exposes two separate checks.

### Health

```text
GET /health/
```

This confirms that Django can respond to a request.

A successful health check does not prove that PostgreSQL and OpenSearch are available.

### Readiness

```text
GET /ready/
```

This checks PostgreSQL connectivity and OpenSearch cluster health.

It returns HTTP 200 when both dependencies are considered ready, and HTTP 503 when a required dependency is unavailable.

This distinction is useful during deployment troubleshooting:

```text
/health/  -> Is the application responding?

/ready/   -> Can the application reach its dependencies?
```

---

# HTTP Endpoints

The current URL configuration exposes these routes.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Render the dashboard |
| GET | `/admin/` | Django administration |
| GET | `/health/` | Basic application health |
| GET | `/ready/` | PostgreSQL and OpenSearch readiness |
| Search endpoint | `/api/search/` | Search indexed documents |
| GET | `/api/monitoring/outbox/` | Read outbox operational metrics |
| Crawl-job endpoint | `/api/crawl/jobs/` | Inspect crawl jobs |
| Crawl-job creation endpoint | `/api/crawl/jobs/create/` | Submit a crawl job |

The exact request payloads, validation rules, and response schemas should be taken from the implementation and its tests rather than inferred from the route names.

---

# Local Development

## Requirements

- Python 3.13
- Git
- Docker Desktop
- Docker Compose
- Visual Studio Code (recommended)

The local development environment uses PostgreSQL and OpenSearch through Docker Compose.

## 1. Clone the repository

```powershell
git clone https://github.com/harishwaranvijayakumar-code/indexforge.git
cd indexforge
```

## 2. Create a virtual environment

```powershell
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use the execution-policy procedure appropriate for your development environment.

## 3. Configure environment variables

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` for local development.

The default local services are configured to use:

```text
PostgreSQL: 127.0.0.1:5432
OpenSearch: http://127.0.0.1:9200
```

Replace local secrets with suitable development-only values. Never commit `.env`.

## 4. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. Start PostgreSQL and OpenSearch

```powershell
docker compose up -d postgres opensearch
```

Inspect the services:

```powershell
docker compose ps
```

PostgreSQL and OpenSearch should become healthy before proceeding.

## 6. Initialize the database

```powershell
python manage.py migrate
python manage.py check
```

## 7. Start the Django application

```powershell
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/health/
```

Readiness check:

```text
http://127.0.0.1:8000/ready/
```

The readiness endpoint requires both local services to be available.

---

# Configuration

IndexForge uses environment variables for application, database, search, and processing configuration.

The repository contains `.env.example` as a template for local development. Actual secrets and hosted connection details belong in the relevant environment configuration, not in version control.

## Django settings

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django cryptographic secret |
| `DJANGO_DEBUG` | Enables or disables debug mode |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated permitted hostnames |
| `CSRF_TRUSTED_ORIGINS` | Trusted origins for CSRF checks |
| `DJANGO_SECURE_SSL_REDIRECT` | Controls HTTPS redirection in production |

## PostgreSQL settings

| Variable | Purpose |
|---|---|
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | Database username |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_HOST` | Database hostname |
| `POSTGRES_PORT` | Database port |
| `POSTGRES_SSLMODE` | PostgreSQL TLS mode |

For a hosted database, use the connection details and TLS requirements provided by the database service.

## OpenSearch settings

| Variable | Purpose |
|---|---|
| `OPENSEARCH_URL` | OpenSearch HTTP or HTTPS endpoint |
| `OPENSEARCH_USERNAME` | Optional basic-auth username |
| `OPENSEARCH_PASSWORD` | Optional basic-auth password |
| `OPENSEARCH_INDEX` | Configured index name |
| `OPENSEARCH_ALIAS` | Configured search alias |

For hosted OpenSearch, use the HTTPS endpoint and the authentication configuration provided by the service.

## Outbox processing settings

| Variable | Purpose |
|---|---|
| `OUTBOX_BATCH_SIZE` | Maximum number of events processed in a batch |
| `OUTBOX_MAX_ATTEMPTS` | Configured retry-attempt limit |
| `OUTBOX_RETRY_BASE_SECONDS` | Base retry delay |
| `OUTBOX_PROCESSING_TIMEOUT_SECONDS` | Processing timeout configuration |

The values in `.env.example` are development defaults, not universal production recommendations.

---

# Running Background Workers

IndexForge uses management commands rather than relying on a web request to perform all indexing and crawling work.

## Process indexing events

```powershell
python manage.py process_outbox
```

This processes one batch and exits.

## Process a crawl job

```powershell
python manage.py process_crawl_jobs --once
```

This processes at most one queued crawl job and exits.

## Run a continuous crawl worker

```powershell
python manage.py process_crawl_jobs
```

This polls for jobs continuously. It is appropriate only when the deployment environment can keep the process running.

## Retry and index lifecycle commands

The repository also includes:

```text
retry_outbox
rebuild_index
rollback_index
```

Inspect command help before executing an operational action:

```powershell
python manage.py help retry_outbox
python manage.py help rebuild_index
python manage.py help rollback_index
```

A management command being available locally does not mean it is automatically scheduled in the hosted environment.

---

# Testing and CI

IndexForge uses pytest, pytest-django, Django system checks, and Ruff.

The GitHub Actions workflow runs on pushes and pull requests.

The CI pipeline includes:

1. Checking out the repository.
2. Installing Python dependencies.
3. Starting a PostgreSQL service for tests.
4. Checking Ruff formatting.
5. Running Ruff lint checks.
6. Running Django system checks.
7. Collecting static files.
8. Applying database migrations.
9. Running the test suite.

## Run formatting checks

```powershell
ruff format --check .
```

## Run lint checks

```powershell
ruff check .
```

## Check Django configuration

```powershell
python manage.py check
```

## Collect static files

```powershell
python manage.py collectstatic --noinput
```

## Run tests

```powershell
python -m pytest -q
```

## Check the working tree

```powershell
git diff --check
git status
```

The tests validate application behavior, but the deployment should also be checked against the actual hosted PostgreSQL and OpenSearch services.

A passing local test suite is not a substitute for checking the live application's health, readiness, indexing behavior, and crawl processing.

---

# Experiments and Performance

IndexForge is intended to demonstrate engineering decisions through reproducible observations rather than unqualified claims.

## Experiment 1: Indexing Reliability

**Question:** What happens when PostgreSQL commits a source-data change but OpenSearch is unavailable?

**Failure mode:**

```text
Source transaction commits
          |
          v
Indexing request fails
          |
          v
Outbox event remains recoverable
```

**Mechanisms under investigation:**

- Transactional outbox
- Batch processing
- Retry handling
- Processing claims
- Operational monitoring

**What to measure:**

- Number of source records committed
- Number of outbox events created
- Number of events successfully processed
- Number of failed or deferred events
- Time until a committed document becomes searchable

## Experiment 2: Duplicate Processing

**Question:** Can repeated processing of the same event produce an incorrect search representation?

**Mechanisms under investigation:**

- Stable document identity
- Repeatable indexing operations
- Transactional state changes
- Claim-token protection

**What to measure:**

- Source document count
- Search document count
- Duplicate logical document count
- Final document contents after repeated processing

## Experiment 3: Index Rebuilding

**Question:** Can IndexForge build and activate a replacement index without prematurely replacing the current search target?

**Mechanisms under investigation:**

- Candidate index construction
- Population and validation
- Alias switching
- Rollback

**What to measure:**

- Active alias before and after rebuild
- Document counts in each index
- Search behavior during the operation
- Outcome when a replacement cannot be validated
- Recovery behavior after rollback

## Experiment 4: Website Crawling

**Question:** Can permitted web content be collected and made searchable through the existing ingestion pipeline?

**Mechanisms under investigation:**

- Seed URL validation
- Host restrictions
- Page limits
- Content extraction
- Crawl-job state transitions
- Document indexing

**What to measure:**

- Pages attempted
- Pages successfully fetched
- Documents created
- Indexing events processed
- Crawl-job completion or failure
- Total elapsed time

## Recorded Load-Test Baseline

A previous local load test recorded the following results:

| Metric | Recorded value |
|---|---:|
| Concurrent users | 5 |
| Duration | 60 seconds |
| Requests | 183 |
| Failed requests | 0 |
| Throughput | 3.19 requests/second |
| Average latency | 36 ms |
| Median latency | 31 ms |
| 95th-percentile latency | 63 ms |
| Maximum latency | 904 ms |

These values describe one recorded run in its particular environment. They are not a guarantee of production capacity and should not be compared with another environment without recording the test setup, workload, and resource constraints.

---

# Production Deployment

IndexForge is deployed using Render for the Django web service, with Aiven providing the PostgreSQL and OpenSearch services.

## Deployment architecture

```text
GitHub repository
       |
       v
Render Web Service
       |
       v
Gunicorn
       |
       v
Django application
       |
       +----------------------+
       |                      |
       v                      v
Aiven PostgreSQL       Aiven OpenSearch
       |                      |
       v                      v
Source records         Search index
Outbox events          Active alias
Crawl jobs
```

The production application uses environment-based configuration for secrets, database connectivity, allowed hosts, HTTPS, and OpenSearch authentication.

## Build command

The current Render build command is:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput
```

## Start command

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

## Deployment validation

After deployment, verify:

```text
GET /health/
GET /ready/
```

The health endpoint should return HTTP 200 when the application responds.

The readiness endpoint should return HTTP 200 with both PostgreSQL and OpenSearch marked ready.

Also verify that the dashboard loads, static assets render correctly, and the search API can retrieve indexed documents.

## Free-tier architecture

The current demonstration uses free-tier hosting where available.

Important constraints include:

- Render free web services can sleep after inactivity.
- A sleeping web service may take time to wake.
- Aiven free services have resource limits and may power off after inactivity.
- Free services do not provide production-grade availability guarantees.
- Background workers are not continuously available on the Render free instance type.

The database and search engine may therefore be available independently of whether the web service is currently awake.

## Scheduled processing

The existing management commands can be invoked by a scheduled workflow:

```text
process_outbox
process_crawl_jobs --once
```

A scheduled workflow can process queued work periodically, but it is not equivalent to a continuously running worker.

The hosted background-processing schedule must be configured and validated separately. Until that is done, queued indexing events or crawl jobs may remain pending.

---

# Security Considerations

IndexForge is a demonstration search-index management service. It should not be treated as an unrestricted public crawling service or a production search platform without additional operational controls.

## Secrets

- Do not commit `.env`.
- Do not commit database passwords or OpenSearch credentials.
- Store hosted secrets in the hosting provider's environment configuration.
- Use a strong, unique production Django secret.
- Disable Django debug mode in production.

## Database and Search Connectivity

Use the database provider's documented TLS settings.

For OpenSearch, use HTTPS and certificate verification for hosted endpoints. Supply authentication credentials only through environment variables when required by the service.

## Website Crawling

The crawler incorporates restrictions intended to reduce abuse and unsafe network access.

These controls include public DNS validation, destination pinning, same-host restrictions, robots policy, response limits, and redirect handling.

They do not eliminate every possible abuse scenario. Public crawl-job submission should be accompanied by appropriate rate limiting, request validation, resource limits, and operational monitoring.

## Public Access

Making a dashboard section visible to everyone does not automatically mean every operation should be unrestricted.

Visibility, submission permissions, and monitoring access should be evaluated separately. In particular, public crawl submissions can consume network, CPU, database, and search resources.

## Production Limitations

The current free-tier deployment is intended for demonstration and learning. It should not be considered a highly available production service.

---

# Current Limitations

IndexForge is a working application, but several limitations remain relevant to its deployment and operation.

## Periodic Background Processing

The existing worker commands support batch and one-shot processing. The free hosted deployment does not automatically provide a continuously running worker.

Scheduled processing must be configured, and its frequency determines how long indexing events and crawl jobs may remain pending.

## Eventually Consistent Search

A successful source-data transaction does not guarantee immediate search visibility.

Search freshness depends on outbox processing, OpenSearch availability, and the active index state.

## Free-Tier Resource Constraints

The hosted application and its data services operate under constrained resource limits and may sleep or power off after inactivity.

This setup is suitable for a portfolio demonstration, not a service-level availability guarantee.

## Crawl Scope

The crawler is constrained by its implementation and safety rules. It does not crawl the entire internet or guarantee complete extraction from arbitrary websites.

## Operational Validation

The existence of a rebuild, rollback, or recovery command is not by itself proof that every possible failure has been handled. These operations should be tested against reproducible failure cases and their results recorded.

---

# Engineering Roadmap

Future work should prioritize reliability improvements and measurable outcomes rather than adding features without a clear engineering purpose.

## 1. Scheduled Processing Validation

- Configure scheduled outbox processing.
- Configure one-shot crawl-job processing.
- Prevent overlapping scheduled invocations.
- Verify that failed invocations are observable.
- Measure the time from source commit to search visibility.

## 2. Indexing Failure Experiments

- Simulate OpenSearch unavailability.
- Confirm that source records and outbox events remain consistent.
- Restore OpenSearch and process pending events.
- Measure the recovery time and final search state.

## 3. Rebuild Failure Injection

- Introduce a failure before candidate-index validation.
- Confirm that the active alias remains unchanged.
- Test rollback after a replacement has been activated.
- Verify document counts and search behavior after recovery.

## 4. Crawl-Job Reliability

- Exercise failures during fetch and extraction.
- Verify stale-job detection.
- Measure crawl throughput and indexing lag.
- Evaluate the impact of multiple queued jobs.

## 5. Operational Observability

- Record processing latency.
- Track pending and failed outbox events.
- Track the age of the oldest pending event.
- Track crawl-job completion and failure.
- Document the recovery procedure for each failure class.

## 6. Performance Validation

- Repeat load tests under documented conditions.
- Measure search latency and throughput.
- Investigate slow requests and outliers.
- Test indexing and search workloads together.
- Compare performance before and after changes.

## 7. Production Hardening

- Add appropriate rate limits for public operations.
- Review public crawl-submission permissions.
- Validate backup and restore procedures.
- Define operational recovery procedures.
- Evaluate whether a persistent worker and stronger hosting plan are necessary.

---

# Project Methodology

IndexForge follows an investigation-driven engineering process.

```text
1. Identify a real search reliability problem.
2. Understand why the problem exists.
3. Define the correctness invariant.
4. Design the smallest mechanism that addresses it.
5. Implement the mechanism.
6. Reproduce relevant failure modes.
7. Measure the system's behavior.
8. Compare results against the invariant.
9. Identify remaining failure cases.
10. Improve the implementation.
11. Repeat the experiment.
12. Document the evidence and trade-offs.
```

This methodology prevents the project from becoming a feature checklist.

Every major subsystem should exist because it addresses a specific engineering problem.

The transactional outbox exists because independent database and search operations can fail separately. Claim protection exists because workers can become stale. Alias-based index replacement exists because an incomplete replacement should not prematurely become the active search target.

The value of the project lies in understanding and validating these mechanisms.

---

# Project Status

The following major capabilities have been implemented in the current project:

```text
[x] Django application foundation
[x] PostgreSQL-backed persistence
[x] Collections and documents
[x] Transactional outbox
[x] OpenSearch integration
[x] Document search API
[x] Outbox batch processing
[x] Retry and recovery commands
[x] Claim-token protection
[x] Outbox operational monitoring
[x] Index rebuilding
[x] Index rollback
[x] Website crawling workflow
[x] Crawl-job worker
[x] Crawl safety restrictions
[x] Health and readiness endpoints
[x] Operational dashboard
[x] Static asset pipeline
[x] Automated test suite
[x] Ruff formatting and lint checks
[x] GitHub Actions CI workflow
[x] Render web-service deployment
[x] Hosted PostgreSQL connectivity
[x] Hosted OpenSearch connectivity
[x] Public health and readiness validation
```

The deployment's scheduled background-processing workflow and additional public-operation hardening remain separate operational tasks. The presence of a management command should not be interpreted as proof that the command runs automatically in production.

---

# What IndexForge Does Not Claim

IndexForge is not:

- A replacement for Google, Elasticsearch Cloud, or a managed enterprise search platform.
- A general-purpose crawler of the entire internet.
- A guarantee of immediate consistency between PostgreSQL and OpenSearch.
- A guarantee of exactly-once event delivery.
- A production-grade high-availability platform.
- A service with a formal uptime or latency SLA.

The system focuses on making indexing intent durable, processing recoverable, index lifecycle operations controlled, and operational state observable.

---

# Key Takeaway

IndexForge investigates a deceptively difficult engineering problem:

> How do you keep search useful and recoverable when the source data changes, indexing operations fail, background workers become unavailable, and the search index itself needs to be replaced?

The project addresses this through:

```text
PostgreSQL source of truth
          +
Transactional outbox
          +
Retryable indexing
          +
Claim-token protection
          +
Operational monitoring
          +
Controlled index rebuilding
          +
Alias-based activation
          +
Rollback
          +
Restricted website crawling
          +
Automated tests
          +
Deployment validation
```

The central idea is that reliable search requires more than sending documents to a search engine.

The system must preserve the intent to index, tolerate repeated processing, expose failures, recover incomplete work, and manage index replacement without prematurely switching users to an unvalidated search view.

IndexForge exists to make those mechanisms observable, testable, and measurable.