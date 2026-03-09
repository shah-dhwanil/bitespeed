# BiteSpeed — Identity Reconciliation Service

A FastAPI + PostgreSQL microservice that consolidates customer identities across multiple contact records. Given any combination of email address and phone number, the `/identify` endpoint finds all linked contacts, merges separate clusters when necessary, and returns a single unified view of that customer's identity.

**Deployed service:** https://bitespeed-production-160c.up.railway.app/
**Interactive API docs:** https://bitespeed-production-160c.up.railway.app/scalar

---

## Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
  - [1. Clone & install dependencies](#1-clone--install-dependencies)
  - [2. Configure the application](#2-configure-the-application)
  - [3. Run database migrations](#3-run-database-migrations)
  - [4. Start the server](#4-start-the-server)
- [API Reference](#api-reference)
  - [POST /identify](#post-identify)
- [Business Rules](#business-rules)
- [Architecture](#architecture)
- [Running Tests](#running-tests)
- [Documentation](#documentation)

---

## Overview

FluxKart (and similar e-commerce platforms) need to recognise the same customer even when they check out with different emails or phone numbers across different sessions. This service:

1. **Finds** all contact records that match the provided email and/or phone number.
2. **Merges** previously separate identity clusters when a request bridges two of them.
3. **Creates** a new secondary contact when the request introduces previously unseen information.
4. **Returns** a consolidated identity with a deterministic primary (always the oldest contact by creation time).

---

## Project Structure

```
bitespeed/
├── api/
│   ├── app.py              # FastAPI application factory
│   ├── database.py         # asyncpg connection pool manager
│   ├── lifespan.py         # Startup / shutdown lifecycle
│   ├── logging.py          # structlog configuration
│   ├── middleware.py       # Request ID, context & logging middleware
│   ├── sentry.py           # Sentry SDK initialisation
│   ├── controller/
│   │   └── contact.py      # FastAPI router — POST /identify
│   ├── exceptions/
│   │   ├── app.py          # AppException hierarchy (ContactNotFoundException, …)
│   │   └── handler.py      # Global exception → JSON response handlers
│   ├── models/
│   │   ├── contact.py      # Pydantic request / response schemas
│   │   └── errors.py       # Error response schemas
│   ├── repository/
│   │   └── contact.py      # Raw SQL via asyncpg; returns ContactRecord
│   ├── service/
│   │   └── contact.py      # Identity resolution algorithm
│   └── settings/
│       ├── database.py     # DatabaseConfig
│       ├── server.py       # ServerConfig
│       ├── jwt.py          # JWTConfig
│       └── settings.py     # Root Settings (TOML + env vars)
├── migrations/
│   └── V1__create_contact_table.sql   # Flyway migration
├── tests/
│   └── contacts/
│       └── test_identify.py           # 26 scenario-based tests
├── docs/
│   ├── PRD.md              # Product requirements
│   ├── TASKS.md            # Task breakdown
│   └── DESIGN.md           # Technical design & algorithm walkthrough
├── config.toml             # Default configuration values
├── compose.yaml            # Docker Compose — Flyway migrations
└── pyproject.toml          # Dependencies & tooling config
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.12 |
| PostgreSQL | ≥ 17 |
| [uv](https://docs.astral.sh/uv/) | latest |
| Docker (optional) | for Flyway-based migrations |
|Sentry (optional)| Observability|

---

## Getting Started

### 1. Clone & install dependencies

```bash
git clone https://github.com/shah-dhwanil/bitespeed.git
cd bitespeed
uv sync               # installs runtime deps
uv sync --group dev   # also installs test deps (httpx, pytest, pytest-asyncio)
```

### 2. Configure the application

Key settings in `config.toml` (all overridable via environment variables prefixed `BITESPEED_`):

```toml
[postgres]
pool_min_size = 1
pool_max_size = 2
```

Minimum environment variables required to run:

```bash
export BITESPEED_POSTGRES__HOST=localhost
export BITESPEED_POSTGRES__PORT=5432
export BITESPEED_POSTGRES__NAME=bitespeed
export BITESPEED_POSTGRES__USER=postgres
export BITESPEED_POSTGRES__PASSWORD=your_password
```

### 3. Run database migrations

**Using Docker Compose (recommended):**

```bash
export FLYWAY_URL=jdbc:postgresql://localhost:5432/bitespeed
export FLYWAY_USER=postgres
export FLYWAY_PASSWORD=your_password
docker compose run --rm flyway
```

**Manually (psql):**

```bash
psql -h localhost -U postgres -d bitespeed -f migrations/V1__create_contact_table.sql
```

### 4. Start the server

```bash
uv run python -m api.main
```

The server starts on `http://127.0.0.1:8000` by default.

Available endpoints:

| URL | Description |
|-----|-------------|
| `POST /identify` | Identity reconciliation |
| `GET /health` | Health check + DB pool stats |
| `GET /scalar` | Interactive API docs (Scalar UI) |
| `GET /openapi.json` | OpenAPI schema |

---

## API Reference

### POST /identify

Identifies and consolidates a customer contact.

**Request**

```http
POST /identify
Content-Type: application/json
```

```json
{
  "email": "lorraine@hillvalley.edu",
  "phoneNumber": "+919876543210"
}
```

- At least one of `email` or `phoneNumber` must be provided.
- `email` must be a valid e-mail address (validated by Pydantic's `EmailStr`). An invalid format such as `"not-an-email"` returns `422`.
- `phoneNumber` must be a parseable phone number (validated by `pydantic-extra-types` + `phonenumbers`). A value like `"abc"` or `"00000"` returns `422`. Supply numbers in **E.164 format** (e.g. `+919876543210`) for guaranteed acceptance; if no country code is provided the number is parsed assuming the **IN (India)** region.

**Validation error example** (`422 Unprocessable Content`):

```json
{
  "status_code": 422,
  "title": "Validation Error",
  "detail": "One or more fields failed validation",
  "errors": [
    {
      "type": "value_error",
      "message": "value is not a valid phone number",
      "field": "body.phoneNumber",
      "value": "abc"
    }
  ]
}
```

**Response `200 OK`**

```json
{
  "contact": {
    "primaryContatcId": 1,
    "emails": [
      "lorraine@hillvalley.edu",
      "mcfly@hillvalley.edu"
    ],
    "phoneNumbers": [
      "+919876543210"
    ],
    "secondaryContactIds": [23]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `primaryContatcId` | `int` | ID of the oldest (primary) contact in the cluster |
| `emails` | `string[]` | All unique emails; primary's email is first |
| `phoneNumbers` | `string[]` | All unique phone numbers; primary's phone is first |
| `secondaryContactIds` | `int[]` | IDs of all secondary contacts in the cluster |

**Error responses**

| Status | Cause |
|--------|-------|
| `422` | `email` / `phoneNumber` both absent, email format invalid, or phone number unparseable |
| `500` | Unexpected database error |

---

## Business Rules

| Rule | Behaviour |
|------|-----------|
| **New identity** | No match found → create a new **primary** contact |
| **Known contact, new info** | Match found but request introduces a new email/phone → create a **secondary** contact linked to the primary |
| **Idempotent** | Sending the same email + phone twice produces no extra records |
| **Cluster merge** | Request spans two separate clusters → the **older** primary survives; the newer primary is demoted to secondary and its children are re-parented |
| **Primary ordering** | Oldest contact by `created_at` is always the primary |
| **Soft delete** | Deleted contacts (`deleted_at IS NOT NULL`) are excluded from all lookups |

---

## Architecture

```
Request
  │
  ▼
Controller (api/controller/contact.py)
  │  validates IdentifyRequest (Pydantic)
  ▼
Service (api/service/contact.py)
  │  runs full algorithm inside one DB transaction
  │  raises AppException subclasses on failure
  ▼
Repository (api/repository/contact.py)
  │  raw SQL via asyncpg
  │  wraps all DB errors in ContactDatabaseError
  ▼
PostgreSQL — contact table
```

The service layer owns the transaction boundary. All repository functions accept an `asyncpg.Connection` so the entire identify operation (reads + writes) is atomic.

---

## Running Tests

Tests use an **in-memory database stub** — no real PostgreSQL needed.

```bash
uv run pytest           # run all tests
uv run pytest -v        # verbose output
uv run pytest --tb=short tests/contacts/test_identify.py
```

**Test coverage by scenario:**

| Class | Scenario |
|-------|----------|
| `TestScenario1BrandNewContact` | Empty DB → new primary created |
| `TestScenario2RepeatRequestIsIdempotent` | Same payload twice → no extra record |
| `TestScenario3NewInfoCreatesSecondary` | Shared phone, new email → secondary created; primary's data first |
| `TestScenario4TwoClustersMerge` | Two primaries bridged → oldest survives, newer demoted |
| `TestScenario4bMergeReparentsExistingSecondaries` | Merge re-parents existing secondaries |
| `TestScenario5MatchViaSecondary` | Match on secondary → correct primary resolved |
| `TestHTTPValidation` | Missing/invalid fields → 422 |
| `TestHTTPResponseFormat` | Correct JSON shape, email-only, phone-only, idempotency |