# AGENTS.md

Guidance for any coding/research agent working in this repository.

## Project Snapshot

- Project: **Dispatch**
- Type: Internal high-volume email platform (single namespace, not SaaS)
- Delivery backbone: AWS SES (sole provider)
- Architecture posture: deliverability-first, fail-closed defaults
- Current repo state: documentation/spec-first; implementation is being scaffolded

## Core Docs to Read First

1. `README.md`
2. `Docs/02_system_design.md`
3. `Docs/03_code_architecture.md`
4. `Docs/01_schema.sql`
5. `Docs/04_operations_runbook.md`
6. `Docs/backend_sprints/README.md`
7. `Docs/frontend_sprints/README.md`

## Technical Baseline

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 async
- Workers: Celery + Redis
- Database: PostgreSQL 15+
- Frontend baseline: Next.js 16 (App Router) + TypeScript
- Infra: AWS ECS Fargate + Terraform

## Non-Negotiable Engineering Rules

1. Business rules live in service layer, not routes.
2. Repositories stay CRUD-focused.
3. Idempotency is required for retries, workers, and webhook handlers.
4. Default to fail-closed behavior for delivery guardrails.
5. No silent exception swallowing.
6. Do not leak secrets or PII in logs.
7. Add/adjust tests with every behavior change.

## Data and Domain Invariants

- `suppression_entries.email` must remain globally unique.
- Suppressed/unsubscribed contacts must never be sent to.
- Message state transitions are one-way (`queued -> sending -> sent|failed|...`).
- Circuit breaker state must gate sending per scope.
- Audit history is append-only.

## Working Conventions for Agents

1. Prefer minimal, targeted edits over broad refactors.
2. Keep docs and architecture references consistent when changing versions or stack choices.
3. Use typed errors and centralized mapping in API layers.
4. Keep long-running/async work in workers, not API request paths.
5. If requirements conflict, preserve deliverability and safety guarantees first.

## Environment and Execution Rules (Mandatory)

1. For backend work, always use the project Python virtual environment (`venv`) for installs, tests, migrations, scripts, and all backend tooling.
2. Never install backend dependencies globally on the host Python.
3. Before running backend tests, Alembic migrations, linting, type-checking, Celery workers, dev scripts, or one-off Python commands, activate the project venv and run tools from that venv.
4. Backend package installation, test execution, migration generation/application, and backend maintenance commands must happen from the active venv or via the venv executables directly.

PowerShell baseline flow:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest
```

If the project uses `pyproject.toml`/Poetry/uv in a given branch, use the repo-defined flow, but still keep execution inside the project-managed virtual environment.

If the shell is not activated, call the venv executables explicitly, for example:

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\alembic upgrade head
```

## Sprint Rule Compliance (Strict)

Agents must strictly follow the sprint rules and conventions in:

- `C:\Users\khali\Desktop\Emailing Project\Docs\backend_sprints`
- `C:\Users\khali\Desktop\Emailing Project\Docs\frontend_sprints`

Mandatory behavior:

1. Read the relevant sprint README and active sprint doc before making changes.
2. Treat sprint rules as binding implementation constraints, not suggestions.
3. If a requested change conflicts with sprint rules, flag the conflict explicitly and propose a compliant path.
4. Keep backend and frontend decisions aligned with their respective sprint documentation.

## Documentation Update Policy

When changing architecture, stack versions, or behavior:

- Update the relevant doc in `Docs/`.
- Update `README.md` docs index if you add a new document.
- Keep references synchronized across overview, architecture, and implementation docs.

## Current Priority (Repository Phase)

- Keep strengthening foundational documentation.
- Scaffold implementation directories to match architecture docs when requested:
  - `apps/`, `libs/`, `migrations/`, `infra/`, `tests/`.
