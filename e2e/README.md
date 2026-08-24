# End-to-end test design

Status: implemented and verified locally; remote GitHub Actions execution remains pending.

Date: 2026-08-24

## Purpose

The E2E suite proves that the browser application, Next.js session handling,
FastAPI routes, ownership rules, SQLite persistence, document lifecycle, RAG
flow, exports, and Studio outputs work together. It complements rather than
replaces the focused Vitest and pytest suites.

The first release has two execution tiers:

- A fast, deterministic Chromium suite runs on every pull request and push. It
  needs no API key, public network, or downloaded embedding model once its
  dependencies and Chromium are installed.
- A full-RAG Chromium test runs nightly and on demand. It uses the production
  embedding implementation with a locally generated PDF fixture.

## Goals

- Exercise user-visible workflows through a real browser and real HTTP servers.
- Keep the fast suite reproducible on developer machines and ordinary CI
  runners.
- Cross the real Next.js, FastAPI, authentication, authorization, service, and
  SQLite boundaries.
- Replace only genuinely external or expensive boundaries in the fast tier.
- Give a failed run enough evidence to diagnose without reproducing it first.
- Protect development data by using an isolated runtime directory and ports.

## Non-goals

- Supporting Firefox or WebKit in the first release.
- Depending on live websites, YouTube, a cloud LLM, Ollama, or Redis.
- Treating API interception as the primary E2E mechanism.
- Replacing backend retrieval evaluation, API isolation tests, or frontend
  component tests.
- Adding mobile visual regression coverage in the first release. Existing
  responsive component integration tests remain responsible for that contract.

## Architecture

The fast tier follows this path:

~~~text
Playwright Chromium
    -> Next.js on 127.0.0.1:3100
    -> FastAPI on 127.0.0.1:8100
    -> production routers, ownership checks, and services
    -> run-specific SQLite database and upload directory
    -> deterministic substitutes at external/expensive boundaries only
~~~

Ports 3100 and 8100 deliberately differ from the normal development ports.
Playwright must fail if either E2E port is already occupied; it must never reuse
an arbitrary existing server and accidentally exercise a developer database.

The full-RAG tier follows the same path but uses the production embedding
service. It sets LLM_MODE=none so the test measures ingestion and retrieval
rather than the availability or wording of a remote language model.

### Repository layout

The implemented layout is:

~~~text
e2e/
  README.md
  package.json
  package-lock.json
  playwright.config.ts
  support/
    api.ts
    diagnostics.ts
    fixtures.ts
    runtime.ts
  tests/
    auth.spec.ts
    projects.spec.ts
    sources.spec.ts
    chat.spec.ts
    studio-and-settings.spec.ts
    full-rag.spec.ts

backend/
  requirements-e2e.txt
  requirements-e2e-rag.txt
  scripts/
    e2e_server.py
    e2e_services.py

.github/workflows/e2e.yml
~~~

The root README testing section lists the supported commands. Playwright
reports, traces, videos, screenshots, runtime databases, generated PDFs, and
uploads live under output/e2e and remain ignored.

## Service boundaries

The ingest and query routers use lazy, cached dependency providers for
DocumentService and RAGService. This avoids importing or creating the embedding
model until an ingest or query request needs it, and lets FastAPI dependency
overrides select deterministic E2E services:

- Production requests receive the same concrete services and behavior as now.
- App startup and auth/project requests do not load an embedding model.
- The E2E server overrides the providers without changing any HTTP route.
- RAGService accepts injected embedding and LLM services, matching the injection
  support DocumentService already provides.
- DocumentService and RAGService import the production EmbeddingService only
  when no embedding implementation was injected. Importing either service with
  a deterministic implementation therefore does not require torch or
  sentence-transformers to be installed.

The fast E2E service set uses:

- A normalized token-hash embedding implementation. The same stable algorithm
  embeds chunks and queries, so the real retrieval and citation flow remains
  exercised.
- The real PDF adapter and chunking service against a generated, valid PDF.
- Fixed URL content and YouTube transcript adapters. This keeps the document
  lifecycle real without making public websites part of the pass condition.
- The normal no-provider LLM fallback. Responses must report the fallback model
  rather than pretending that a remote model answered.

The fast suite does not intercept application API calls. Route interception is
reserved for a test that explicitly verifies a browser-only failure state and
cannot be produced through the controlled backend.

## Runtime and data isolation

Each run creates a random identifier and resolves its runtime root beneath:

~~~text
<repository>/output/e2e/<run-id>/
  opennotebook.db
  uploads/
  generated/
  server-logs/
~~~

Before removing or resetting anything, the server and teardown code must resolve
the absolute path and verify that it remains beneath the repository's
output/e2e directory. A missing, empty, root, home, repository-root, data, or
uploads target is an error, never a cleanup request.

The server starts with:

- APP_ENV=test
- ALLOW_PUBLIC_REGISTRATION=true
- a run-specific DB_PATH and DATABASE_URL
- a fixed, non-secret test JWT key
- LLM_MODE=none
- RATE_LIMIT_ENABLED=false
- CORS limited to the E2E frontend origin
- one backend worker

The frontend starts with BACKEND_INTERNAL_URL set to the isolated backend's
http://127.0.0.1:8100 origin. Browser requests remain same-origin under `/api`,
and Next.js proxies them to that backend. Startup waits for backend readiness
and the frontend login page; a timeout reports both server logs instead of
continuing with a half-started stack.

Every test owns a unique username and email derived from the run and test IDs.
Tests do not depend on execution order. The authentication specs create their
state through the UI. Other specs may use Playwright's API request context for
setup, then perform the behavior under test through the UI. Assertions verify
both the user-visible result and, where valuable, the persisted API response.

The Playwright suite uses one worker initially. Unique identities still remain
mandatory so later parallelization does not require rewriting the fixtures.
The runtime is deleted after a successful local run. CI retains it only when a
failure occurs and uploads it as a short-lived diagnostic artifact.

## Fast-suite workflows

The approved logical coverage is implemented as small independent Playwright
tests rather than one long scenario:

### Authentication and session

1. An anonymous workspace visit redirects to the login page.
2. A new account can register, enter the workspace, and remain signed in after
   reload.
3. A wrong password displays the backend error and creates no browser session.
4. Signing out clears the token and prevents back-navigation to the protected
   workspace.

### Projects and ownership

5. A user can create and select a project, and the project reloads from the
   backend after a page refresh.
6. Switching between two accounts never exposes the other account's projects
   or documents.

### Sources

7. A generated PDF can be uploaded, progress reaches ready, its protected bytes
   can be previewed, and deletion removes it.
8. A controlled URL can be imported, reaches ready, appears in source search,
   and can be removed.
9. A controlled YouTube URL creates a transcript source and reaches ready.

### Chat and conversations

10. Asking a ready source a question creates a conversation, persists the user
    and assistant messages, and renders a citation to that source after reload.
11. A conversation can be created, renamed, selected, and deleted.

### Studio, export, and preferences

12. Independent tests exercise the approved output group: mind-map rendering,
    report download, project/conversation export, video-summary fallback,
    audio unsupported fallback, and persisted dark-theme selection. These are
    separate Playwright test cases even though they form one logical coverage
    group, so one broken output does not hide the others.

Native browser confirmation and download events are handled before the action
that triggers them. Audio tests install a deterministic speech-capability state
before application code runs; they do not depend on host audio hardware.

## Full-RAG workflow

The full-rag test is excluded from the fast project unless FULL_RAG_E2E=1. It:

1. Starts from a new account and project.
2. Generates and uploads a small PDF containing a unique fact and identifier.
3. Polls the document status until it is ready, with a model-aware timeout.
4. Asks a question whose answer requires the unique fact.
5. Verifies that the response cites the uploaded PDF and that the retrieved
   passage contains the identifier.
6. Reloads the conversation and verifies that both messages persisted.

The assertion targets the retrieved fact and citation, not exact fallback prose.
The test neither requires nor calls an external LLM. Its sentence-transformers
model cache is shared between nightly runs, but the database and uploads are not.

## Synchronization and failure handling

Tests must not use fixed sleeps. They synchronize through:

- Playwright locator auto-waiting for UI state.
- Named HTTP responses for create, update, delete, query, and export actions.
- Polling the document status endpoint until ready or error.
- Browser download and confirmation-dialog events.
- Explicit reload assertions for persistence.

An unexpected page error, console error, unhandled request failure, or backend
5xx fails the active test. Expected negative cases register their expected 4xx
response before performing the action.

Local runs use zero retries. CI permits one retry so a trace can distinguish an
environmental browser failure, but both attempts remain visible. On failure the
suite retains:

- screenshot
- video
- Playwright trace
- HTML report
- frontend and backend logs
- the isolated runtime database and generated fixture, within artifact policy

No credentials, developer database, shared upload, or model file is included in
an artifact.

## Commands

From the E2E package:

~~~bash
npm ci
npx playwright install chromium
npm test
npm run test:headed
npm run test:debug
npm run test:full-rag
~~~

The default test command runs only the deterministic Chromium project. The
headed and debug commands use the same isolated backend. The full-rag command
sets the explicit opt-in and uses the production embedding provider.

## CI

The GitHub Actions workflow has two jobs:

- Fast E2E runs for pull requests and pushes. It installs the frontend, the
  standalone E2E package, Chromium, and the reduced backend E2E requirements.
  Those requirements deliberately exclude torch and sentence-transformers.
- Full RAG runs on a nightly schedule and workflow dispatch. It installs the
  additional embedding dependencies, restores the Hugging Face and
  sentence-transformers model cache,
  and runs only full-rag.spec.ts.

Both jobs upload diagnostics only on failure. Neither job reads API-provider
secrets. Existing frontend Vitest, lint, and backend pytest commands remain
separate validation gates.

## Local verification

The following fresh local checks completed on 2026-08-24:

- New backend unit tests prove service creation is lazy and dependency
  overrides select the deterministic services.
- The supported native ARM64 backend image built successfully, and its full
  suite passed **760 tests** with 1 skip in 216.16 seconds after integrating
  the durable ingestion worker from the latest `master`.
- `cd frontend && npm test` passed **41 files / 412 tests**; `npm run lint`,
  `npm run build`, and `cd e2e && npm run typecheck` also passed.
- `cd e2e && npm test` passed **33 tests** in 1.6 minutes, with no unexpected
  skips. It intentionally excludes exactly one opt-in test: `full-rag.spec.ts`.
- `cd e2e && npm run test:full-rag` passed **1 test** using production-aligned
  Torch 2.13, Transformers 5.5, and sentence-transformers 5.7. The latest
  warm-cache run took 32.6 seconds; the browser workflow itself took 10.7
  seconds and used `LLM_MODE=none`.
- The tracked-artifact audit contains no runtime database, uploads, model cache,
  Playwright report, trace, screenshot, or video.

The workflow has not yet executed remotely in GitHub Actions; that remains the
only workflow-level validation pending.

## Expected limitations

- The deterministic suite proves integration around external services, not the
  correctness or availability of live websites, YouTube, or a cloud model.
- Chromium is the only browser gate in the first release.
- The nightly test covers real PDF ingestion and retrieval, not live URL or
  YouTube availability.
- Visual appearance remains covered by component contracts and manual review,
  not pixel snapshots.
