# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**dispatch** is an internal high-volume email platform targeting 1M+ sends/day, built on AWS SES as the sole sending backbone. The platform is split into a **control plane we build** (contacts, campaigns, suppression, analytics, ML) and a **delivery plane we rent** (AWS SES). Single namespace — no multi-tenancy, no org scoping, no plan tiers.

**Current repo state:** documentation/spec-first. No implementation code exists yet. The `Docs/` folder is the source of truth for what to build. Before writing any code, read the relevant sprint doc and the docs it references.

## Development Commands

### Backend (Python)

Bootstrap the virtual environment once per machine:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

All backend commands run from the `backend/` directory (where `pyproject.toml` and `Makefile` live). Always activate the project virtual environment first — never install packages globally.

This rule applies to every backend-related command, including tests, migrations, linting, type-checking, Celery workers, dev scripts, one-off Python commands, dependency installs, and Alembic operations. Use the venv executables directly if the shell is not activated, for example `.\.venv\Scripts\python -m pytest` or `.\.venv\Scripts\alembic upgrade head`.

```bash
make dev                          # Start full local environment (Docker Compose)
alembic upgrade head              # Apply DB migrations
alembic revision --autogenerate -m "<description>"  # Generate migration

ruff check .                      # Lint (CI-enforced)
mypy apps libs tests              # Type-check (CI-enforced, strict mode)

pytest tests/unit/                # Run unit tests only
pytest tests/integration/         # Run integration tests (requires Postgres + Redis)
pytest tests/e2e/                 # Run e2e tests (requires LocalStack)
pytest tests/unit/path/test_file.py::test_name  # Run a single test

celery -A apps.workers.send worker -Q send.<domain>   # Start a send worker
celery -A apps.workers.events worker                  # Start event worker
```

Coverage thresholds (95%+ enforced in CI) apply to: `libs/core/suppression/*`, `libs/core/circuit_breaker/*`, `libs/core/campaigns/service.py`, `apps/webhook/handlers.py`, `libs/ses_client/client.py`.

### Frontend (Node / pnpm)

The frontend lives in `apps/web/`. All frontend commands run from that directory.

```bash
pnpm install                      # Install dependencies
pnpm dev                          # Start dev server (Turbopack)
pnpm build                        # Production build
pnpm lint                         # ESLint
pnpm type-check                   # tsc --noEmit

pnpm test                         # Vitest unit/component tests
pnpm test src/app/(dashboard)/campaigns/**   # Run tests for one route
pnpm run e2e                      # Playwright E2E suite (requires dev server)
pnpm run e2e:headed               # Playwright with browser visible
pnpm run a11y                     # axe-core accessibility sweep (tests/e2e/a11y_sweep.spec.ts)
```

## Architecture

### Monorepo Structure

```
apps/       — Deployable services (api, workers, webhook, scheduler, web)
libs/       — Shared libraries (core, ses_client, dns_provisioner, ml, schemas)
migrations/ — Alembic migration files
infra/      — Terraform IaC, Dockerfiles
tests/      — unit / integration / e2e
```

**Import rule:** `apps/*` may import from `libs/*` but never from each other. `libs/core` is the only lib that imports from the schema.

### Service Layer Pattern

Every domain in `libs/core/<domain>/` has exactly four files:

- `models.py` — SQLAlchemy ORM models
- `schemas.py` — Pydantic DTOs
- `service.py` — **All business rules live here exclusively**
- `repository.py` — Pure CRUD; no business logic

FastAPI routes call service methods only — never the ORM directly. Workers follow the same pattern and construct services the same way routes do.

Every service is exposed via a module-level `get_<domain>_service()` factory decorated with `@lru_cache(maxsize=1)`. Tests call the paired `reset_<domain>_service_cache()` in teardown to avoid singleton leakage between test cases.

External dependencies (SES, DNS, MX lookup) are injected via `Protocol` interfaces. Service `__init__` methods accept them as `... | None = None` and fall back to a `Noop*` default — so production callers need no arguments and tests inject fakes. Result objects are `@dataclass(slots=True)` value types, not raw dicts.

### Celery Queue Architecture

One Celery queue per sending domain (`send.<domain_name>`). This is the key design decision enabling per-domain circuit breaking. Workers use `task_acks_late=True` and `worker_prefetch_multiplier=1`.

Every send task is **idempotent**: it accepts a `message_id`, reloads the entity, and returns early if `status != 'queued'`. Status transitions are one-way: `queued → sending → sent|failed`.

### Rate Limiting

Enforced **inside the task** via a Redis Lua token bucket (`libs/core/throttle/token_bucket.py`), not by Celery's native `rate_limit`. Default: 150 sends/hour per domain.

### Circuit Breakers

Four scopes: domain, IP pool, sender profile, account. Thresholds are intentionally **half** of SES's warning levels (1.5% bounce / 0.05% complaint at domain level) because by the time AWS warns, reputation damage has already occurred. Evaluated every 60 seconds. Fail-closed: unknown state → pause sending.

### Event Pipeline

SES → SNS → webhook receiver (separate deploy, so campaign API traffic can't starve it) → `events.ses.incoming` Celery queue → event worker → suppression write + metrics update → circuit breaker evaluator.

Suppression is written twice: at segment evaluation (batch filter) and at send time (per-message final check).

### Pre-Send Validation

Seven gates split across two phases:
- **At import time (Gates 1–3):** format, SMTP validation, role-account filter
- **At send time (Gates 4–7):** suppression check, SES account-level suppression, spam trap heuristics, ML spam scorer (reject if score > 0.2)

### Error Taxonomy

All errors inherit from `dispatchError` (`libs/core/errors.py`). Routes map typed domain exceptions to HTTP codes in a single global handler (`apps/api/exception_handlers.py`) — routes never catch domain exceptions themselves.

### Configuration

All config via environment variables through a single `Settings` class (`libs/core/config.py`, Pydantic `BaseSettings`). No `os.getenv()` scattered through the codebase.

## Critical Data Invariants

These must hold across all code paths (enforced by DB constraints and application logic):

- Every message has a non-null `domain_id` and `sender_profile_id`
- `suppression_entries (email)` is UNIQUE — no duplicates
- Contacts with `lifecycle_status = 'suppressed'` or `'unsubscribed'` cannot receive messages
- `segment_snapshots` is **append-only** — no UPDATE paths
- `circuit_breaker_state = 'open'` pauses all sends in its scope
- `audit_log` entries are never deleted (DB user has INSERT-only permission)

## Frontend Architecture

Frontend lives at `apps/web/` and uses Next.js 16 App Router. Key conventions:

- **Server Components by default.** Add `"use client"` only where interactivity (state, effects, browser APIs) is required. Keep providers as deep as possible.
- **Route groups:** `(auth)/` for login/MFA, `(dashboard)/` for all product pages. Groups don't appear in URLs.
- **Colocation:** route-specific UI goes in `_components/`, route-specific data helpers go in `_lib/`. These private folders are not routable.
- **Reusable primitives:** `src/components/ui/` (shadcn/ui generated), `src/components/shared/` (project-level shared), `src/components/charts/`.
- **API layer:** `src/lib/api/server.ts` for server-side fetches, `src/lib/api/client.ts` for client-side. Never call the backend API directly from a Server Component without going through `src/lib/api/`.
- **Import alias:** `@/*` maps to `src/*`. Use it consistently.
- **Data fetching in routes:** sensitive/credentialed fetches happen in Server Components. Use `loading.tsx` and `error.tsx` at the route-segment level.
- **`app/api/` route handlers** are only for frontend-adjacent concerns (health, session, BFF needs) — not duplicates of backend API routes.

## Code Conventions

- Every `.py` file begins with `from __future__ import annotations`.
- `ruff` + `mypy --strict` must pass before merging. Run them from `backend/` — same as CI.
- Prefer keyword-only arguments (`*,` separator) on service and repository method signatures to prevent positional mistakes at call sites.

## Testing Approach

- Unit tests (70%): pure service logic; use `sqlite+aiosqlite` via pytest `tmp_path` — no Postgres, no Redis. The `auth_test_context` fixture in `tests/conftest.py` wires everything up.
- Integration tests (25%): real Postgres in Docker, real Redis; SES mocked at contract level
- E2E tests (5%): full request through FastAPI → Celery → fake SES → webhook via LocalStack
- Test DB wiped between each test via transaction rollback; no shared state
- Fake adapters (e.g. `FakeSesTransport`, `FakeDNSVerificationAdapter`) live in `tests/fixtures/` and `tests/conftest.py`; use them instead of `unittest.mock`.

## Sprint Rule Compliance

Before writing any code, read:
1. `Docs/backend_sprints/README.md` or `Docs/frontend_sprints/README.md` (sprint index)
2. The active sprint doc (e.g., `Docs/backend_sprints/sprint_01_core_infrastructure.md`)
3. The docs listed in the sprint's "Docs to Follow" section

Sprint docs are binding constraints, not suggestions. If a requested change conflicts with a sprint rule, flag the conflict and propose a compliant path. Backend and frontend sprint numbers are aligned — they merge together.

**Current scope:** Phase 1 (MVP, Sprints 00–11) + Phase 2 (Scale, Sprints 12–15). Sprints 16–21 (observability, ML, 1M/day hardening) are deferred.

## Documentation Update Policy

When changing architecture, stack versions, or behavior: update the relevant doc in `Docs/` and keep `README.md` docs index synchronized if a new document is added.
