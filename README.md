# dispatch

**dispatch** is an internal high-volume email platform built to send 1 million+ emails per day to inbox — not spam folder. It is a single-namespace system with no multi-tenancy, no plan tiers, and no third-party ESP dependency beyond AWS SES for SMTP transport.

---

## Architecture

The platform is split into two distinct planes:

**Control plane (built here)**
- Domain provisioning, warmup scheduling, and reputation monitoring
- Contact and list management with full import provenance
- Campaign authoring, scheduling, pausing, and resumption
- Segmentation with snapshot isolation at send time
- Platform-wide suppression list synced to SES account suppression
- Analytics, circuit breaker state, and per-domain health dashboards
- ML layer — spam scoring, reply intent classification, anomaly detection (Phase 3+)

**Delivery plane (AWS SES)**
- SES is the sole SMTP backbone; raw SMTP is never touched
- SES fires bounce, complaint, delivery, open, and click events to SNS
- SNS delivers to a dedicated webhook receiver that writes suppression and metrics in real time

### Deliverability model

Inbox placement at scale is an operational discipline, not a configuration problem. Every architectural decision reflects that premise:

| Signal | Threshold enforced by dispatch |
|---|---|
| Bounce rate | < 1.5% per domain (SES warns at 5%) |
| Complaint rate | < 0.05% per domain (Gmail hard-enforces at 0.3%) |
| Send rate | Token-bucket per domain (Redis Lua), default 150/hr |
| Circuit breakers | 4 scopes — domain, IP pool, sender profile, account. Fail-closed. |
| Pre-send gates | 7 gates across import time (3) and send time (4) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | Python 3.12 · FastAPI · SQLAlchemy 2.0 async |
| Workers | Celery · Redis |
| Database | PostgreSQL 15+ |
| Email transport | AWS SES (boto3) |
| DNS | Cloudflare API · Route 53 |
| Frontend | Next.js 16 · TypeScript · App Router |
| Infrastructure | AWS ECS Fargate · RDS · ElastiCache · Terraform |
| Observability | OpenTelemetry · Datadog |
| ML | scikit-learn · XGBoost · DistilBERT |

---

## Repository Structure

```
.
├── apps/                   Deployable services
│   ├── api/                FastAPI control-plane API
│   ├── workers/            Celery workers (send, event, import, metrics)
│   ├── webhook/            SNS webhook receiver (separate deploy)
│   ├── scheduler/          Celery Beat scheduler
│   └── web/                Next.js frontend (App Router)
│
├── libs/                   Shared libraries
│   ├── core/               Business logic (domain, service, repository layers)
│   ├── ses_client/         Typed SES wrapper
│   ├── dns_provisioner/    Cloudflare + Route 53 provisioning adapters
│   ├── ml/                 ML inference pipeline
│   └── schemas/            Shared Pydantic contracts
│
├── migrations/             Alembic migration files
├── infra/                  Terraform IaC and Dockerfiles
├── tests/                  unit / integration / e2e
└── Docs/                   Architecture and sprint documentation
```

**Import rule:** `apps/*` may import from `libs/*` but never from each other. `libs/core` is the only lib that imports from the schema lib.

---

## Getting Started

### Prerequisites

- Python 3.12
- Node.js 20+ and pnpm
- Docker Desktop (with WSL2 backend on Windows)
- GNU Make

### Backend

```bash
# From the repository root
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -e .[dev]

# Start full local environment (PostgreSQL, Redis, LocalStack)
make dev

# Apply database migrations
alembic upgrade head
```

### Frontend

```bash
cd apps/web

pnpm install
pnpm dev          # Start dev server on http://localhost:3000
```

---

## Development Commands

### Backend (run from `backend/`)

```bash
ruff check .                          # Lint (CI-enforced)
mypy apps libs tests                  # Type-check in strict mode (CI-enforced)

pytest tests/unit/                    # Unit tests (SQLite, no external deps)
pytest tests/integration/             # Integration tests (requires Postgres + Redis)
pytest tests/e2e/                     # End-to-end tests (requires LocalStack)

# Run a specific test
pytest tests/unit/path/test_file.py::test_name

# Coverage (80% global minimum, 95%+ on critical modules)
pytest --cov=apps --cov=libs --cov-report=term-missing tests/

# Migrations
alembic revision --autogenerate -m "<description>"
alembic upgrade head
alembic downgrade -1
```

### Frontend (run from `apps/web/`)

```bash
pnpm lint                # ESLint
pnpm type-check          # tsc --noEmit
pnpm test                # Vitest unit/component tests
pnpm build               # Production build

pnpm run e2e             # Playwright end-to-end suite
pnpm run e2e:headed      # Playwright with browser visible
pnpm run a11y            # axe-core accessibility sweep
```

---

## Scale Roadmap

| Phase | Volume | Sprints |
|---|---|---|
| MVP | 10K – 75K sends/day | 00 – 11 |
| Scale | 75K – 300K sends/day | 12 – 16 |
| ML | 300K – 600K sends/day | 17 – 19 |
| Full | 600K – 1M+ sends/day | 20 – 21 |

### Backend Sprint Status

#### Phase 1 — MVP (Sprints 00–11)

| # | Sprint | Status |
|---|---|---|
| 00 | Foundation & Monorepo Bootstrap | Done |
| 01 | Core Infrastructure: Config, DB, Migrations, Errors, Logging | Done |
| 02 | Auth, Users & API Keys | Done |
| 03 | Domains, Sender Profiles & IP Pools | Done |
| 04 | Contacts, Lists & Preferences | Done |
| 05 | CSV Import Pipeline (Gates 1–3) | Done |
| 06 | Templates & Template Versioning | Done |
| 07 | Segments & Segment Snapshots | Done |
| 08 | Suppression Service | Done |
| 09 | SES Client & Send Pipeline (Gates 4–7) | Done |
| 10 | Webhook Receiver & Event Worker | Done |
| 11 | Analytics & Dashboard APIs | Done |

#### Phase 2 — Scale (Sprints 12–16)

| # | Sprint | Status |
|---|---|---|
| 12 | Per-Domain Queues & Token Bucket Rate Limiting | Pending |
| 13 | Circuit Breakers (4 Scopes) & Evaluator | Pending |
| 14 | Automated Domain Provisioning | Pending |
| 15 | Warmup Engine & Postmaster Tools | Pending |
| 16 | Full Observability Stack | Pending |

---

## Documentation

Full architecture and design documentation lives in [`Docs/`](Docs/).

| Document | Contents |
|---|---|
| [00_project_overview.md](Docs/00_project_overview.md) | Plain-English project description |
| [01_schema.sql](Docs/01_schema.sql) | Complete PostgreSQL schema (39 tables) |
| [02_system_design.md](Docs/02_system_design.md) | Master system design document |
| [05_goals_and_non_goals.md](Docs/05_goals_and_non_goals.md) | Goals, non-goals, and success metrics |
| [06_system_context.md](Docs/06_system_context.md) | Actors, external systems, data flows |
| [07_functional_requirements.md](Docs/07_functional_requirements.md) | Functional requirements |
| [08_non_functional_requirements.md](Docs/08_non_functional_requirements.md) | Performance, availability, security requirements |
| [09_data_model.md](Docs/09_data_model.md) | Schema groups, invariants, partitioning strategy |
| [10_delivery_pipeline.md](Docs/10_delivery_pipeline.md) | Send task flow and seven-gate pre-send validation |
| [11_operational_guardrails.md](Docs/11_operational_guardrails.md) | Circuit breakers and rate limiting design |
| [12_ml_services.md](Docs/12_ml_services.md) | ML models and inference pipeline |
| [13_deployment_infrastructure.md](Docs/13_deployment_infrastructure.md) | VPC topology, environments, IaC |
| [14_security.md](Docs/14_security.md) | Auth, encryption, secrets management, compliance |
| [15_observability.md](Docs/15_observability.md) | Metrics, logging, tracing, alerting |
| [16_rollout_plan.md](Docs/16_rollout_plan.md) | Phase-by-phase rollout plan |
| [17_fastapi_documentation.md](Docs/17_fastapi_documentation.md) | FastAPI implementation guidance |
| [18_nextjs_documentation.md](Docs/18_nextjs_documentation.md) | Next.js App Router implementation guidance |
| [19_backend_file_structure.md](Docs/19_backend_file_structure.md) | Backend folder/file blueprint |
| [20_frontend_file_structure.md](Docs/20_frontend_file_structure.md) | Frontend folder/file blueprint |
| [21_domain_model.md](Docs/21_domain_model.md) | Business domain model — the contract that aligns backend, frontend, and database |
| [22_aws_deployment_and_configuration.md](Docs/22_aws_deployment_and_configuration.md) | AWS deployment and configuration guide |
| [23_project_technical_explanation.md](Docs/23_project_technical_explanation.md) | Brief technical explanation of the whole project |
| [24_current_changes_tests_and_readiness.md](Docs/24_current_changes_tests_and_readiness.md) | Current implementation changes, test status, known gaps, and marketing-readiness checklist |
| [25_beginner_aws_cloudflare_domain_setup.md](Docs/25_beginner_aws_cloudflare_domain_setup.md) | Beginner AWS, Cloudflare, SES, DNS, and domain buying setup guide |

Sprint plans: [Docs/backend_sprints/](Docs/backend_sprints/) · [Docs/frontend_sprints/](Docs/frontend_sprints/)

---

## Key Design Decisions

**One Celery queue per sending domain.**
The queue name `send.<domain_name>` is the unit of isolation for circuit breaking. If a domain's health degrades, only that queue is paused — the rest continue sending.

**Service layer is the only place for business logic.**
FastAPI routes call service methods. Workers call service methods. Nothing calls the ORM directly. Every domain in `libs/core/<domain>/` has exactly four files: `models.py`, `schemas.py`, `service.py`, `repository.py`.

**Fail-closed circuit breakers.**
Unknown state means stop sending. Thresholds are set at half of SES's warning levels because by the time AWS warns, reputation damage has already occurred.

**Suppression checked twice.**
At segment evaluation (batch filter before campaign launch) and at send time (per-message final check). A contact suppressed between launch and delivery will not receive the message.

**Idempotent send tasks.**
Every send task accepts a `message_id`, reloads the entity, and returns early if `status != 'queued'`. Duplicate Celery deliveries are safe.
