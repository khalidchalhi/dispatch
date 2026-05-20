# Current Changes, Tests, and Readiness

Date: 2026-05-19

This document is a working status note for the recent Dispatch implementation pass. It summarizes the backend and frontend changes made, the tests and fixes applied, the remaining issues found during verification, and what the app still needs before moving into marketing-facing work.

## Project Context

Dispatch is an internal high-volume email platform built around AWS SES, strict deliverability controls, and fail-closed safety defaults. The work in this pass focused on closing frontend/backend API gaps, adding missing operational endpoints, making the local development database usable, and hardening the frontend test harness so the application can be exercised without AWS while SES setup is still in progress.

## Backend Changes Made

### Auth and Users

- Added backend/frontend parity for API key listing.
  - Frontend expects `GET /auth/api-keys`.
  - Backend already had `/users/me/api-keys`.
  - The API now supports the frontend contract without breaking the existing user-scoped route.
- Added `GET /users/{id}` so admins can fetch any user by ID, not only `/users/me`.
- Added `POST /users/{id}/reset-mfa` so admins can reset MFA for a specific user.
- Added and adjusted backend integration coverage for the auth/user API behavior.

### Domains, Warmup, and DNS Zones

- Added `GET /domains/{id}/warmup` to return the warmup schedule for a domain.
- Added `POST /domains/{id}/warmup/extend` to extend warmup by a requested number of days.
- Added `GET /domains/zones` so the provisioning wizard can list DNS provider zones.
- Kept Postmaster work out of scope for now, per request.
- Added backend tests around the new domain warmup and zone behavior.

### Ops and Public Contracts

- Added `GET /ops/provisioning` for the provisioning audit log.
- Added backend support for updating domain throttle/rate limit through `POST /domains/{id}/throttle`.
- Added frontend internal route support for:
  - `POST /api/domains/{id}/throttle`
  - `POST /api/circuit-breakers/{id}/reset`
- Aligned unsubscribe behavior around the public unsubscribe contract.
  - The frontend now uses the public unsubscribe flow consistently.
  - Backend public unsubscribe tests were updated for the chosen contract.

### Database and Migrations

- Created and used the project virtual environment for backend work.
- Connected to the local PostgreSQL database named `dispatch`.
- Used the requested local database credentials without writing them into committed runtime config.
- Ran Alembic migrations to the current head.
- Patched migration `0006_sprint12_domain_rate_limit.py` so it safely handles a local database where `domains.rate_limit_per_hour` already exists.

## Frontend Changes Made

### API and Local Test Harness

- Added a shared mock API fallback at `frontend/src/lib/api/mock-api.ts`.
- Updated server and client API helpers so local browser tests can fall back to mock API data when `DISPATCH_WEB_ENABLE_DEV_SESSION` is enabled and the backend is unavailable.
- Added mock-backed data for domains, zones, warmup, provisioning, ops queues, circuit breakers, analytics, contacts, lists, sender profiles, templates, segments, suppression, campaigns, messages, and preflight checks.
- Added Playwright authentication setup so e2e tests can reuse a dev session instead of repeating sign-in setup in every spec.
- Updated Playwright standalone server handling so production-build e2e tests can run against the Next.js standalone output.

### Domain Provisioning and Operations UI

- Fixed the domain provisioning wizard so provider zone loading is stable and does not trigger React state update warnings.
- Added request tracking for zone loading to avoid stale provider responses.
- Fixed nullable DNS provider handling in TypeScript.
- Improved warmup tab behavior and labels, including the dynamic "Extend by N days" action.
- Added provisioning step label aliases so backend step names render clearly in the frontend.
- Mapped circuit breaker state from API fields consistently across domain pages and sender profile pages.
- Added missing accessibility labels in provisioning diagnostics and circuit breaker controls.

### Campaigns, Templates, Analytics, and Design Polish

- Fixed campaign monitor refresh and polling behavior so filters and message refreshes are stable.
- Adjusted campaign review code to avoid callback and render warnings.
- Added compatibility props for template version history.
- Improved analytics copy from "sends today" to "warmup today" where the UI was referring to warmup-domain data.
- Adjusted danger colors and primary button contrast tokens for better accessibility.
- Added accessible labeling to campaign KPI tiles.
- Added or adjusted frontend tests for campaign monitoring, domain provisioning, and internal API routes.

## Task Tracking Updated

The relevant items in `tasks.md` were checked with `X` after implementation. Notes were also added where useful so the Obsidian task list can continue acting as the working tracker.

Completed task groups include:

- Auth and Users
- Domains - Warmup and DNS zones
- Ops endpoints
- Public unsubscribe parity

## Tests and Verification Run

### Backend

The backend was verified using the project virtual environment and local PostgreSQL database.

Passing backend results:

- Alembic migration upgrade to head completed.
- Unit tests: 161 passed.
- Integration API tests: 40 passed.
- Integration core tests: 7 passed, 2 skipped.
- Integration database, DNS, and webhook tests: 7 passed, 1 skipped.
- Worker tests: 35 passed.
- Local fake-backed e2e tests: 3 passed.

Backend issues still present but not introduced by this pass:

- Full `ruff` currently reports broad pre-existing lint debt.
- Full `mypy` currently reports broad pre-existing type debt.
- `alembic check` still reports metadata drift because the Alembic environment does not import all model metadata consistently.

### Frontend

Passing frontend results from this pass:

- `pnpm typecheck` passed.
- `pnpm lint` passed.
- `pnpm test` passed.
  - 29 test files.
  - 395 tests.
- `pnpm build` passed.
- Focused Playwright suites passed for:
  - Campaign launch and monitor flows.
  - Domain auto-provisioning flows.
  - Several domain, reputation, warmup, circuit breaker, and throughput flows after targeted fixes.

Frontend issues still in progress:

- The full Playwright e2e suite was not fully green yet.
- Latest full-suite snapshot had 211 passing tests and 30 failing tests.
- The remaining failures are mostly in:
  - Accessibility timing assertions where axe runs before the page heading is visible.
  - Public unsubscribe landmark coverage.
  - Contact, segment, and template 404 expectations where the protected dashboard shell renders a not-found screen instead of returning a raw 404 response.
  - Template editor route behavior caused by a render-time state update in the preview pane.
  - Suppression UI assertions that need table-scoped selectors and a mock drift count.

## Fixes Applied From Test Findings

- Made backend migration behavior safer for existing local columns.
- Fixed several React lint and state-update issues in frontend components.
- Added accessible labels to controls that tests and assistive technology need to identify.
- Improved mock API coverage so frontend tests do not require AWS, SES, Route 53, Cloudflare, or the live backend for every route.
- Adjusted Playwright setup to better match a logged-in local development session.
- Fixed internal route tests around throttle and circuit breaker reset behavior.

## What Still Needs To Run the App Smoothly

### Local Backend

- PostgreSQL 15+ running locally.
- Database named `dispatch`.
- Database credentials configured in the backend environment.
- Redis running locally for worker and queue behavior.
- Backend virtual environment created and activated before any backend command.
- Backend dependencies installed into the project virtual environment.
- Alembic migrations applied to the local database.
- Required environment variables configured, especially database URL, Redis URL, auth/session secrets, and dev-safe feature flags.

### Local Frontend

- Node.js 20+ and pnpm available.
- Frontend dependencies installed.
- API base URL configured to point at the local backend when testing real backend behavior.
- `DISPATCH_WEB_ENABLE_DEV_SESSION=1` can be used for local/dev browser testing while auth and AWS wiring are still being finalized.
- Full Playwright e2e suite should be brought green after the remaining known failures are fixed.

### AWS and External Services

Before production-like marketing or sending work, the app still needs:

- AWS SES account and sending identity setup.
- Verified sending domains.
- DKIM, SPF, DMARC, and tracking DNS records configured.
- SNS topics and webhook subscriptions for SES delivery, bounce, complaint, open, and click events.
- Redis-backed token bucket behavior tested outside mocks.
- Worker processes running for send, import, webhook, metrics, and scheduled jobs.
- Secrets management for AWS, DNS providers, session signing, and any webhook verification keys.
- Observability wiring for logs, metrics, traces, and alerts.

## Readiness for Marketing Work

Marketing-facing work can start once the core local app is stable enough to support repeated campaign setup and review flows. The main prerequisites are:

- Full frontend e2e suite green, or at least the campaign, templates, contacts, suppression, unsubscribe, domains, and analytics flows green.
- Real backend and frontend running together locally without relying only on mock fallback data.
- Unsubscribe and suppression behavior verified end to end.
- Template preview and versioning verified because marketing work depends heavily on safe template editing.
- Contact import and segment builder verified with realistic test data.
- Domain warmup, throttle, and circuit breaker views working because they determine whether marketing sends should proceed.
- Clear local run instructions for backend, frontend, workers, Redis, and Postgres.

After that, the next marketing-focused work can safely include:

- Campaign creation workflow polish.
- Template library expansion.
- Preference and unsubscribe page polish.
- Segment presets for marketing audiences.
- Campaign QA checklist screens.
- Deliverability dashboards tailored for marketing operators.
- UTM and tracking conventions.
- Seed inbox and warmup reporting improvements.

## Recommended Next Steps

1. Finish the remaining frontend e2e fixes from the latest Playwright run.
2. Re-run frontend lint, typecheck, unit tests, build, and full e2e.
3. Decide whether to address backend `ruff`, `mypy`, and Alembic metadata drift now or track them as separate cleanup tasks.
4. Write a single local runbook for starting backend, frontend, Redis, Postgres, and workers together.
5. Begin marketing workflow polish after unsubscribe, templates, contacts, suppression, and campaign creation are green end to end.
