---
title: Emailing Project — Task Tracker
tags:
  - tasks
  - emailing
  - active
date: 2026-05-07
aliases:
  - Dispatch Tasks
---

# Emailing Project — Task Tracker

← [[Projects/Emailing Project/brief|Brief]] · [[Projects/Emailing Project/architecture|Architecture]] · [[Projects/Emailing Project/decisions|Decisions]]

> Last updated: 2026-05-20
> ✅ Current no-Postmaster endpoint scope completed
> ✅ Backend migrations ran locally against PostgreSQL `dispatch`
> ✅ Backend test suites passed for local/non-AWS scope
> ✅ Frontend lint, typecheck, unit tests, and build passed
> ⚠️ Full Playwright e2e still needs cleanup: latest run had 211 passing / 30 failing
> ✅ Frontend Sprints 03–14 complete + Sprint 15 warmup UI wired
> ✅ Backend Sprints 12–14 complete — token bucket + circuit breakers + domain provisioning live
> ✅ Sprint 15 warmup engine complete
> Remaining: Sprint 15 Postmaster deferred · frontend e2e cleanup · backend lint/type cleanup · infra fixes

> [!info] Current Phase — Local Testing + AWS Setup
> - Core endpoint parity work requested in this session is implemented.
> - Local backend migrations/tests passed without AWS.
> - Frontend app builds and unit tests pass.
> - Full browser e2e is partially green and needs the known cleanup items below.
> - **Waiting on AWS** — SES, DNS, SNS, worker secrets, and provider credentials are still needed for production-like sending tests.
> - Purpose: cashflow tool — not an H.V.A company product

---

## ✅ Codex Update — 2026-05-19

> [!success] Implemented in this pass
> - Auth/User parity:
>   - `GET /auth/api-keys`
>   - `GET /users/{id}`
>   - `POST /users/{id}/reset-mfa`
> - Domains warmup and DNS zones:
>   - `GET /domains/{id}/warmup`
>   - `POST /domains/{id}/warmup/extend`
>   - `GET /domains/zones`
> - Ops/public parity:
>   - `GET /ops/provisioning`
>   - `POST /domains/{id}/throttle` backend support
>   - `POST /api/domains/{id}/throttle` frontend internal route
>   - `POST /api/circuit-breakers/{id}/reset` frontend internal route
>   - Public unsubscribe contract aligned
> - Local test harness:
>   - Added frontend mock API fallback for non-AWS local browser testing.
>   - Added Playwright dev-session auth setup.
>   - Updated Next standalone e2e runner.
> - Tracking:
>   - Added status document: `Docs/24_current_changes_tests_and_readiness.md`
>   - Added the new doc to `README.md`

> [!check] Tests run
> - Backend Alembic migration upgrade to head: passed.
> - Backend unit tests: 161 passed.
> - Backend integration API tests: 40 passed.
> - Backend integration core tests: 7 passed, 2 skipped.
> - Backend DB/DNS/webhook integration tests: 7 passed, 1 skipped.
> - Backend worker tests: 35 passed.
> - Backend local fake-backed e2e tests: 3 passed.
> - Frontend `pnpm typecheck`: passed.
> - Frontend `pnpm lint`: passed.
> - Frontend `pnpm test`: 29 files / 395 tests passed.
> - Frontend `pnpm build`: passed.
> - Focused Playwright suites passed for campaign, domain provisioning, warmup/reputation/throughput/circuit-breaker areas.

> [!warning] Known issues still to fix
> - Full frontend Playwright e2e is not fully green yet: latest full run had 211 passing / 30 failing.
> - Remaining browser failures are mostly:
>   - a11y timing where axe runs before the page heading is visible
>   - public unsubscribe missing a main landmark
>   - contact/segment/template 404 tests expecting HTTP 404 while the dashboard shell renders a not-found screen
>   - template preview pane render-time state update
>   - suppression tests needing table-scoped selectors and a non-zero mock drift count
> - Backend `ruff` has broad pre-existing lint debt.
> - Backend `mypy` has broad pre-existing type debt.
> - `alembic check` still reports metadata drift because Alembic metadata import coverage is incomplete.

> [!todo] Before marketing work
> - Finish remaining Playwright e2e fixes.
> - Re-run frontend lint, typecheck, unit tests, build, and full e2e.
> - Decide whether backend lint/type/Alembic metadata cleanup is part of the next sprint or a separate cleanup pass.
> - Write a single local runbook for backend + frontend + Redis + Postgres + workers.
> - Configure AWS SES, verified domains, DKIM/SPF/DMARC, SNS webhooks, secrets, and worker deployment before production-like sending.

---

## 🔴 Active Blockers — Fix These First

> [!danger] These 5 blockers prevent any meaningful integration. Nothing ships until cleared.

- [x] **B1 — Analytics tests failing** — ✅ Fixed `service.py:133` and `:202`, all 5 tests passing
- [x] **B2 — Frontend dashboards are mock-backed** — ✅ All 4 dashboard pages wired to real API
	- [x] `(dashboard)/domains/page.tsx` → ✅ `serverJson(ENDPOINTS.domains.list)`
	- [x] `(dashboard)/contacts/page.tsx` → ✅ `serverJson(ENDPOINTS.contacts.list)`
	- [x] `(dashboard)/analytics/page.tsx` → ✅ real rollup endpoint calls + `GET /analytics/reputation`
	- [x] `(dashboard)/campaigns/[campaignId]/page.tsx` → ✅ real `GET /campaigns/{id}` + live status polling
- [x] **B3 — Missing backend endpoints for current no-Postmaster scope** — ✅ Auth/Users, Warmup, DNS zones, Ops, throttle/reset, and public unsubscribe parity done
- [x] **B4 — Ops scripts are 0-byte stubs** — ✅ Implemented `pause_account.py`, `pause_campaign.py`, `retire_domain.py`
- [x] **B5 — Playwright e2e broken** — ✅ Fixed `playwright.config.ts:14` + `run-e2e.mjs:6` to use `corepack pnpm`

---

## 🔴 Missing Backend Endpoints (B3 Detail)

> All routes referenced by `frontend/src/lib/api/endpoints.ts` but absent from backend routers.

### Campaigns ✅ DONE
- [x] `GET /campaigns` — ✅
- [x] `POST /campaigns` — ✅
- [x] `GET /campaigns/{id}` — ✅
- [x] `PATCH /campaigns/{id}` — ✅
- [x] `POST /campaigns/{id}/preflight` — ✅
- [x] `GET /campaigns/{id}/messages` — ✅
- [x] `POST /campaigns/{id}/messages/{msgId}/requeue` — ✅

### Domains — Warmup & Postmaster
- [x] `GET /domains/{id}/warmup` — get warmup schedule for a domain
- [x] `POST /domains/{id}/warmup/extend` — extend warmup by N days
- [ ] `GET /domains/{id}/postmaster` — get Google Postmaster metrics
- [ ] `POST /domains/{id}/postmaster/connect` — OAuth connect to Postmaster
- [x] `GET /domains/zones` — list DNS provider zones (for provisioning wizard)

> [!note] Postmaster intentionally deferred
> User requested no Postmaster work for now. Keep these unchecked until AWS/Google Postmaster setup is ready.

### Contacts & Imports ✅ DONE
- [x] `POST /contacts/bulk-import` — ✅ alias added → `/imports`
- [x] `GET /contacts/bulk-import/{id}/status` — ✅
- [x] `GET /contacts/bulk-import/{id}/errors` — ✅
- [x] `POST /contacts/bulk-unsubscribe` — ✅

### Segments ✅ DONE
- [x] `POST /segments/{id}/duplicate` — ✅
- [x] `POST /segments/{id}/evaluate` — ✅ (aliased from `preview`)

### Suppression ✅ DONE
- [x] `POST /suppression/export` — ✅
- [x] `GET /suppression/{id}/reveal` — ✅ admin-only

### Templates ✅ DONE
- [x] `GET /templates/merge-tags` — ✅
- [x] `POST /templates/{id}/versions/{version}/publish` — ✅

### Auth & Users
- [x] `GET /auth/api-keys` — frontend expects this; backend uses `/users/me/api-keys` — align
- [x] `POST /users/{id}/reset-mfa` — admin reset MFA for any user (backend lacks this)
- [x] `GET /users/{id}` — get any user by ID (not just `/users/me`)

### Ops
- [x] `GET /ops/provisioning` — provisioning audit log
- [x] `POST /api/domains/{id}/throttle` — update domain rate limit (Next.js internal route, not proxied to backend)
- [x] `POST /api/circuit-breakers/{id}/reset` — reset a breaker (Next.js internal route, not implemented)

### Public
- [x] Fix unsubscribe parity: frontend POSTs to `/unsubscribe` with body token; backend has `/u/{token}` path param and `/contacts/unsubscribe/public` — pick one contract and align both sides

---

## 🟡 Frontend Rewiring — Sprint by Sprint

> UI exists but is mock-backed. Each item = replace mock source with real API call.

### Sprint 03 — Domains & Sender Profiles
- [x] `domains/page.tsx` — ✅ replaced `domainList` mock with `serverJson(ENDPOINTS.domains.list)`
- [x] `domains/[domainId]/page.tsx` — ✅ replaced `getDomainDetail` mock with `serverJson(ENDPOINTS.domains.detail(domainId))`
- [x] `sender-profiles/page.tsx` — ✅ replaced `senderProfiles` mock with `serverJson(ENDPOINTS.senderProfiles.list)`
- [x] Wire `verify-button.tsx` — ✅ wired to `POST /domains/{id}/verify` with loading state + toast

### Sprint 04 — Contacts & Lists ✅ DONE
- [x] `contacts/page.tsx` — ✅ replaced mock with `serverJson(ENDPOINTS.contacts.list)`
- [x] `lists/page.tsx` — ✅ replaced mock with `serverJson(ENDPOINTS.lists.list)`
- [x] Fix unsubscribe route parity — ✅ unified to `POST /contacts/unsubscribe/public` with `{ token }` body

### Sprint 05 — CSV Import Wizard ✅ DONE
- [x] Add `/contacts/bulk-import` → `/imports` route alias in backend — ✅
- [x] Wire `progress-step.tsx` polling to real `/imports/{id}` status — ✅ polls every 2s until completed/failed
- [x] Wire `review-step.tsx` error table to real `/imports/{id}/errors` — ✅

### Sprint 06 — Templates ✅ DONE
- [x] Replace `mockTemplates` in `templates/page.tsx` — ✅ `serverJson(ENDPOINTS.templates.list)`
- [x] Replace `mockMergeTags` — ✅ real fetch to `GET /templates/merge-tags`
- [x] Wire publish action in `template-workspace.tsx` — ✅ `POST /templates/{id}/versions/{version}/publish` with loading + toast

### Sprint 07 — Segments ✅ DONE
- [x] Replace `segments-manager.tsx` mock source — ✅ `serverJson(ENDPOINTS.segments.list)`
- [x] Wire "Duplicate" button — ✅ `POST /segments/{id}/duplicate` + refetch on success
- [x] Wire `preview-panel.tsx` — ✅ `POST /segments/{id}/evaluate` fires on filter change

### Sprint 08 — Suppression ✅ DONE
- [x] Replace `suppression/page.tsx` mock list — ✅ real fetch
- [x] Wire export button — ✅ `POST /suppression/export` → Blob URL file download
- [x] Wire reveal action — ✅ `GET /suppression/{id}/reveal` admin-only with role guard

### Sprint 09 — Campaign Authoring ✅ DONE
- [x] Wire multi-step wizard to real campaign create + preflight endpoints ✅
- [x] Replace mock `templates`/`senders`/`segments` in wizard steps with real API calls ✅
- [x] Wire "Launch" confirm button to `POST /campaigns/{id}/launch` ✅

### Sprint 10 — Campaign Monitoring ✅ DONE
- [x] Replace `campaign-monitor.tsx` mock polling with real `GET /campaigns/{id}` + live status polling ✅
- [x] Wire message inspector drawer to `GET /campaigns/{id}/messages` ✅
- [x] Wire requeue button to `POST /campaigns/{id}/messages/{msgId}/requeue` ✅

### Sprint 11 — Analytics ✅ DONE
- [x] Replace `analytics-queries.ts` imports in `analytics/page.tsx` with real rollup endpoint calls ✅
- [x] Replace reputation page mock with real `GET /analytics/reputation` ✅
- [x] Freshness banner reflects actual `last_updated` timestamp from API response ✅

### Sprint 12 — Throttle & Queue Viewer ✅ DONE
- [x] Implement Next.js `/api/domains/{id}/throttle` route → proxy to backend throttle update ✅
- [x] Replace `ops-queries.ts` mock in `ops/queues/page.tsx` with real queue depth API ✅
- [x] Wire throughput-tab save button to throttle update endpoint ✅

### Sprint 13 — Circuit Breakers Console ✅ DONE
- [x] Implement Next.js `/api/circuit-breakers/{id}/reset` → proxy to backend ✅
- [x] Replace `getBreakerMatrix` mock in `ops/circuit-breakers/page.tsx` with real breaker state fetch ✅
- [x] Wire reset-dialog confirm to real reset endpoint ✅

### Sprint 14 — Domain Provisioning UI ✅ DONE
- [x] Replace `getMockZones` in provisioning wizard with real `GET /domains/zones` ✅
- [x] Replace `getMockProvisioningAttempt` with real provision status from backend ✅
- [x] Replace `getMockProvisioningAudit` in `ops/provisioning/page.tsx` with real audit log ✅

### Sprint 15 — Warmup Done / Postmaster Deferred
- [x] Replace warmup data in `domains/[domainId]` with real `GET /domains/{id}/warmup` ✅
- [x] Wire "Extend" button to `POST /domains/{id}/warmup/extend` ✅
- [ ] Replace Postmaster data with real `GET /domains/{id}/postmaster`
- [ ] Wire Postmaster OAuth connect flow to `POST /domains/{id}/postmaster/connect`

> [!note] Codex update
> Warmup is implemented and tested for local scope. Postmaster remains deferred by request.

---

## 🟡 Backend Scale — Sprints 12–15

### Sprint 12 — Per-Domain Queues & Token Bucket ✅ DONE
- [x] Per-domain Celery queue routing via custom `task_routes` callable reading `domain_id` ✅
- [x] Redis Lua token bucket: `try_take(n=1)` → `(allowed, retry_after_seconds)` — atomic, tested ✅
- [x] `send_message` task: call bucket first → re-enqueue with `countdown=retry_after` if denied ✅
- [x] Expose bucket metrics (tokens available, denial count) via metrics module ✅
- [x] `scripts/ops/provision_domains.py` — spawn Celery worker config per active domain ✅
- [x] Load test: two domains at 10× and 1× their limits — zero cross-contamination verified ✅

### Sprint 13 — Circuit Breakers ✅ DONE
- [x] `CircuitBreakerState` model + state machine: `closed → open → half_open → closed` ✅
- [x] `is_open(scope_type, scope_id)` → bool with 10s Redis cache ✅
- [x] `trip(scope, reason)` and `reset(scope, by_user)` — both fully audited ✅
- [x] Thresholds: Domain (bounce ≥1.5% OR complaint ≥0.05% / 24h), IP pool (same), Sender profile (bounce ≥2%), Account (bounce ≥1%) ✅
- [x] Celery Beat evaluator: `evaluate_circuit_breakers` every 60s — reads rolling metrics, trips on threshold ✅
- [x] `send_message` checks all 4 scopes before suppression check — fail-closed on Redis error ✅
- [x] Add backend admin router endpoints: list breakers, get status, reset with justification ✅
- [x] `scripts/ops/pause_account.py` ✅
- [x] `scripts/ops/pause_campaign.py` ✅

### Sprint 14 — Automated Domain Provisioning ✅ DONE
- [x] `DNSProvisioner` protocol: `create_record`, `update_record`, `delete_record`, `verify_record`, `list_zones` ✅
- [x] Cloudflare driver: idempotent upserts, API token from AWS Secrets Manager ✅
- [x] Route 53 driver: `ChangeResourceRecordSets` batch via boto3 ✅
- [x] SES identity automation: `create_email_identity` + DKIM + per-domain ConfigurationSet + MAIL FROM ✅
- [x] `provision_domain` Celery task: create identity → fetch DKIM tokens → write DNS → poll verification → set `verified` ✅
- [x] `POST /domains/{id}/provision` API endpoint ✅
- [x] `GET /domains/zones` API endpoint ✅
- [x] `GET /ops/provisioning` audit log endpoint ✅
- [x] `scripts/ops/retire_domain.py` ✅
- [x] Idempotent rollback: partial failure leaves domain in `provisioning_failed` with typed reason ✅

### Sprint 15 — Warmup Engine Done / Postmaster Deferred
- [x] `domains.warmup_schedule` JSON column + `domains.warmup_stage` enum: `none | warming | graduated` ✅
- [x] Warmup template generator based on ESP best practices (50→100→500→1K→5K) ✅
- [x] Nightly Celery task: compute daily budget per warming domain ✅
- [x] Token bucket daily cap reads from warmup budget instead of static value ✅
- [x] Graduation: mark `graduated` after N clean days; extend warmup on bad reputation signals ✅
- [x] `GET /domains/{id}/warmup` + `POST /domains/{id}/warmup/extend` API endpoints ✅
- [ ] Google Postmaster Tools OAuth 2.0 flow (platform-level auth)
- [ ] Daily Postmaster poll: domain reputation, spam rate, auth results → persist to `postmaster_metrics` table
- [ ] Feed Postmaster signals into circuit breaker evaluator as additional input
- [ ] `GET /domains/{id}/postmaster` + `POST /domains/{id}/postmaster/connect` API endpoints

> [!note] Codex update
> Warmup endpoints are implemented for the current local scope. Postmaster remains deferred until AWS/Google setup is ready.

---

## 🔵 Infrastructure & CI Fixes

- [ ] Add `frontend-ci.yml` GitHub Actions workflow (currently only `backend-ci.yml` exists)
- [ ] Add `web` service to `backend/docker-compose.yml` for full-stack Docker dev environment
- [ ] Fix Sprint 03 partial: align domain lifecycle state machine to spec (add explicit `verifying` state)
- [ ] Migrate `LocalObjectStore` → S3 for production-compatible CSV import storage (Sprint 05 partial)

---

## 🟠 Test Cleanup — Next Codex Pass

- [ ] Fix public unsubscribe page landmark for axe accessibility.
- [ ] Fix template preview pane render-time state update.
- [ ] Update contact/segment/template unknown-resource e2e tests to assert dashboard not-found UI instead of raw HTTP 404 where applicable.
- [ ] Add heading visibility waits before axe scans in timing-sensitive e2e tests.
- [ ] Scope suppression e2e selectors to the suppression table and expose non-zero mock drift count.
- [ ] Add segment evaluate/preview mock fallback if any segment preview browser tests still hit the backend.
- [ ] Re-run full frontend Playwright e2e suite and update this note with final pass/fail count.

---

## 🟠 Backend Cleanup — Later / Separate Scope

- [ ] Clean existing backend `ruff` lint debt.
- [ ] Clean existing backend `mypy` type debt.
- [ ] Fix Alembic metadata import coverage so `alembic check` can run cleanly.

---

## 🔵 Understand the Codebase — Codex Questions

> See full questions + study guide: [[Projects/Emailing Project/codex-questions]]

- [ ] File structure walkthrough — what does each folder/file do?
- [ ] Backend layers deep dive: routes → services → repositories → models → schemas → workers
- [ ] Frontend layers: pages → components → API client → types → dashboard routes
- [ ] How does the worker system work? (Celery + Redis + task routing)
- [ ] What is Redis used for? (queues, throttling, cache, idempotency keys)
- [ ] What is PostgreSQL storing? (all domain entities with relationships)
- [ ] Walk through a full email send flow end-to-end
- [ ] How does SES webhook processing bring bounces/complaints back into the system?
- [ ] What are Alembic migrations and how are DB tables created/versioned?
- [ ] What is the warmup concept — why new domains can't send full volume immediately
- [ ] What security rules matter most? (no PII leaks, hashed API keys, MFA, secrets outside DB)
- [ ] Difference between local dev, Docker dev, and production deployments
- [ ] What parts are fully implemented vs still mock/partial?

---

## ✅ Done — Phase 1 (Complete)

- [x] Sprint 00: Foundation & Monorepo Bootstrap
- [x] Sprint 01: Core Infrastructure (Config, DB, Migrations, Errors, Logging)
- [x] Sprint 02: Auth, Users & API Keys
- [x] Sprint 03: Domains, Sender Profiles & IP Pools *(Partial — state machine differs)*
- [x] Sprint 04: Contacts, Lists & Preferences
- [x] Sprint 05: CSV Import Pipeline *(Partial — LocalObjectStore not S3)*
- [x] Sprint 06: Templates & Template Versioning
- [x] Sprint 07: Segments & Segment Snapshots
- [x] Sprint 08: Suppression Service
- [x] Sprint 09: SES Client & Send Pipeline
- [x] Sprint 10: Webhook Receiver & Event Worker
- [x] Sprint 11: Analytics & Dashboard APIs

---

## Related

- [[Projects/Emailing Project/aws-cloudflare-domain-setup]] — Beginner AWS, Cloudflare, SES, DNS, and domain buying setup guide
- [[Projects/Emailing Project/codex-questions]] — Full codebase questions for Codex study sessions
- [[Projects/Emailing Project/architecture]] — Technical context (pipeline, circuit breakers, ML)
- [[Projects/Emailing Project/decisions]] — Why each architectural choice was made
- [[Knowledge/Engineering/Email Deliverability]] — Deliverability reference for Sprints 14–15
