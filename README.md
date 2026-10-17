# IndexForge

IndexForge is a search-index management service designed to keep searchable documents synchronized with their PostgreSQL source records.

The project focuses on reliable indexing, observable processing, recovery from failures, and safe index rebuilding.

## Technology Stack

- Python 3.13
- Django 5.2 LTS
- PostgreSQL 17
- OpenSearch 3.9
- HTML, CSS, and JavaScript
- Docker Compose
- pytest and pytest-django
- Ruff
- GitHub Actions

## Current Status

**Milestone M0: Project foundation**

Implemented:
- Django project configuration
- Basic health endpoint at `/health/`
- PostgreSQL connection and initial Django migrations
- Local PostgreSQL and OpenSearch services using Docker Compose
- Ruff formatting and lint configuration
- Automated health endpoint test
- GitHub Actions CI workflow definition

The CI workflow has been created but still needs to run successfully on GitHub.

Not implemented yet:
- Document and collection APIs
- Transactional outbox
- Indexing worker
- Search API
- Operational dashboard
- Safe index rebuilding

## Prerequisites

- Python 3.13
- Git
- Docker Desktop with Docker Compose
- Visual Studio Code

## Local Setup

### 1. Configure environment variables

Copy `.env.example` to `.env`.

In PowerShell:

```powershell
Copy-Item .env.example .env
```

Update the local secret and password values before using the application.

### 2. Install Python dependencies

Create and activate a virtual environment, then run:

```powershell
python -m pip install -r requirements.txt
```

### 3. Start PostgreSQL and OpenSearch

```powershell
docker compose up -d postgres opensearch
```

Check their status:

```powershell
docker compose ps
```

### 4. Initialize the database

```powershell
python manage.py migrate
python manage.py check
```

### 5. Start Django

```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/health/`.

Expected response:

```json
{
  "status": "ok",
  "service": "indexforge"
}
```

### 6. Run quality checks

```powershell
ruff format --check .
ruff check .
python manage.py collectstatic --noinput
python -m pytest
```

## Milestones

- M0: Project foundation and CI.
- M1: Document ingestion and transactional outbox.
- M2: OpenSearch indexing worker and search API.
- M3: Retries, recovery, and observability.
- M4: Safe index rebuilding and rollback.
- M5: Interface refinement and performance testing.
- M6: Deployment, release checks, and documentation.

## Engineering Principles

- PostgreSQL is the source of truth.
- Source writes and outbox events must commit atomically.
- Indexing must tolerate retries and duplicate event delivery.
- A successful source write does not guarantee immediate search visibility.
- Rebuilds must not replace the active index before validation.
- Reliability claims must be supported by measurements and reproducible tests.