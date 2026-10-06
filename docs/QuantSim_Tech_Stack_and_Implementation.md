# QuantSim: Tech Stack and Implementation Guide

> **What this document is.** A plain-language guide to what QuantSim will be built with and how each module will be built.
> It follows the settled architecture (ARC v0.2: 8 microservices, one database per service, an event backbone, outbox, sagas) and the requirements spec (FR/NFR v0.2).
> It does **not** change the architecture. It picks the concrete tools, explains each choice, and shows the implementation step by step.
>
> **Status:** proposal for team review · September 2026
> **Companions:** `QuantSim_Architecture_and_Physical_Design.pdf` (ARC), `QuantSim_Requirements_Specification.pdf` (REQ), `presentation/QuantSim-Pricing-and-Unit-Economics.html` (Pricing)

---

## Contents

1. [The whole stack on one page](#1-the-whole-stack-on-one-page)
2. [Frontend: what we use and why](#2-frontend-what-we-use-and-why)
3. [Backend: what we use and why](#3-backend-what-we-use-and-why)
4. [Why not other languages](#4-why-not-other-languages)
5. [Data and infrastructure](#5-data-and-infrastructure)
6. [The shared service template (built once, used by all 8 services)](#6-the-shared-service-template)
7. [Module-by-module implementation](#7-module-by-module-implementation)
   - [M0 Platform / Identity](#m0--platform--identity)
   - [M1 Market Data](#m1--market-data)
   - [M2 Simulation](#m2--simulation)
   - [M3 Trading](#m3--trading)
   - [M4 Machine Learning](#m4--machine-learning)
   - [M5 Risk & TDA](#m5--risk--tda)
   - [M6 Explainability](#m6--explainability-xai)
   - [M7 Dashboard & Alerting](#m7--dashboard--alerting)
   - [API Gateway](#api-gateway)
8. [One request end to end](#8-one-request-end-to-end)
9. [Free data APIs we plug in](#9-free-data-apis-we-plug-in)
10. [Repository layout](#10-repository-layout)
11. [Testing, CI/CD and observability](#11-testing-cicd-and-observability)
12. [Cost by phase](#12-cost-by-phase)
13. [Changes this proposes to the ARC/REQ documents](#13-changes-this-proposes-to-the-arcreq-documents)
14. [Build order by iteration](#14-build-order-by-iteration)
15. [Glossary](#15-glossary)

---

## 1. The whole stack on one page

| Layer | We use | In one sentence |
|---|---|---|
| **Frontend language** | **TypeScript** | JavaScript with types, so data shapes from the backend are checked at compile time. |
| **Frontend framework** | **React 19 + Vite** | The POC is already React; Vite builds a static site we can host for free. |
| **Styling** | **Tailwind CSS 4** | Already in the POC; utility classes keep a data-dense UI consistent. |
| **Charts** | **Apache ECharts** (heavy charts), **TradingView Lightweight Charts** (candles/replay), **Recharts** (small charts) | Each is used where it is strongest. |
| **Server data in the browser** | **TanStack Query** + generated API clients (**openapi-typescript**, **openapi-fetch**) | Fetching, caching and retrying API data, with types generated from the backend. |
| **UI state** | **Zustand** | Already in the POC; for sidebar, filters, open modals. |
| **Backend language** | **Python 3.12** | All the maths, ML and topology libraries we need exist only (or best) in Python. |
| **Backend framework** | **FastAPI** (async) + **Pydantic v2** | Fast, typed, and generates the OpenAPI contract for every service automatically. |
| **Database access** | **SQLAlchemy 2 (async)** + **asyncpg** + **Alembic** migrations | Standard, well-documented, one migration history per service. |
| **Background jobs** | **Celery 5** on **Redis** | Long jobs (Monte Carlo, TDA, training) run outside the API. |
| **Events between services** | **Redpanda** (Kafka-compatible) + built-in schema registry | Kafka's protocol and guarantees in about a third of the memory. |
| **Main database** | **PostgreSQL 17 + TimescaleDB** (8 logical databases) | Relational + time-series in one engine. |
| **Cache & queue store** | **Redis 8** (two instances: cache and queue) | Fast temporary data and the job queue. |
| **File/object storage** | **Cloudflare R2** (cloud), **SeaweedFS** (local) | Model files, Parquet archives, exports. S3-compatible, free egress. |
| **Gateway** | **Traefik v3** | The single front door: TLS, routing, JWT check, rate limit. |
| **Maths** | NumPy, SciPy, Numba, polars | Fast numerical work. |
| **Topology (TDA)** | giotto-ph, GUDHI, persim | Persistent homology and landscapes. |
| **ML** | scikit-learn, LightGBM/XGBoost, PyTorch, Hugging Face, ONNX Runtime, arch, hmmlearn, MLflow | Models, forecasting, NLP, registry. |
| **Explainability** | SHAP + a hosted LLM with template fallback | Why a number is what it is, in plain English. |
| **Containers** | Docker, Docker Compose (dev/demo), **k3s** (production Kubernetes) | Same images everywhere. |
| **Secrets** | **SOPS + age** (early), **OpenBao** (later) | No passwords in code or images. |
| **Infrastructure as code** | **OpenTofu** | Open-source Terraform fork. |
| **Observability** | OpenTelemetry → Grafana Cloud (free tier), Sentry | Traces, logs, metrics and errors across all services. |
| **CI/CD** | **Jenkins 2.580.1 LTS** (self-hosted in Docker) + GitHub Container Registry + Cloudflare Pages | One pipeline for every branch; images are built once on `develop` and promoted unchanged through DEV → TEST → ACC → PROD. See `docs/ci-cd.md`. |

Everything above is **open source or has a permanent free tier**.

---

## 2. Frontend: what we use and why

### 2.1 The exact frontend stack

| Package | Version line | Used for | Already in POC? |
|---|---|---|---|
| `react`, `react-dom` | 19.x | UI components | ✅ |
| `typescript` | 6.x | Type safety | ✅ |
| `vite` + `@vitejs/plugin-react` | 8.x | Dev server + production build | ✅ |
| `tailwindcss` + `@tailwindcss/vite` | 4.x | Styling | ✅ |
| `react-router-dom` | 7.x | Page routing | ✅ |
| `zustand` | 5.x | UI-only state (sidebar, theme, filters) | ✅ |
| `lucide-react` | – | Icons | ✅ |
| `clsx` | – | Conditional class names | ✅ |
| `recharts` | 3.x | Small charts: KPI sparklines, radar, bars | ✅ |
| **`@tanstack/react-query`** | 5.x | All data coming from the backend | ➕ add |
| **`openapi-typescript`** (dev) + **`openapi-fetch`** | – | Generate typed API clients from each service's OpenAPI | ➕ add |
| **`echarts`** + **`echarts-for-react`** | 5.x / 6.x | Monte Carlo fan chart, correlation heatmap, network graph, persistence diagrams, landscapes | ➕ add |
| **`lightweight-charts`** (TradingView, Apache-2.0) | 5.x | Candlesticks, market replay, trade replay | ➕ add |
| **`react-hook-form`** + **`zod`** | – | Forms (create portfolio, configure simulation) with validation | ➕ add |
| **`@tanstack/react-table`** | 8.x | Big sortable tables (trade log, audit log) | ➕ add |
| `vitest` + `@testing-library/react` | – | Unit/component tests | ➕ add |
| `@playwright/test` | – | End-to-end tests of the demo flow | ➕ add |
| `oxlint` | – | Linting | ✅ |

### 2.2 Why each choice

**React (not Vue, Svelte, Angular).** The POC already has about 40 pages and 30 components in React. Rewriting gains nothing. React also has the most finance-chart wrappers and the largest pool of answers when someone gets stuck.

**Vite single-page app (not Next.js).** ARC §4.1 says the browser is a SPA with *no business logic* that talks to *one origin* (the gateway). Next.js adds server rendering, which needs a running Node.js server. That costs money, adds a second backend language, and gains nothing for a logged-in dashboard that search engines never see. A Vite build is static HTML/JS/CSS that **Cloudflare Pages hosts for free**.

**TanStack Query (replaces the mock layer).** Today every number comes from `src/services/mock`. TanStack Query gives caching, background refresh, retries and loading/error states in one hook:

```ts
// src/services/api/hooks/useSimulationRun.ts
export function useSimulationRun(runId: string) {
  return useQuery({
    queryKey: ['simulation', 'run', runId],
    queryFn: () => api.GET('/v1/simulation/runs/{id}', { params: { path: { id: runId } } }),
    staleTime: 30_000,
  })
}
```

**Generated API clients.** Each FastAPI service publishes an OpenAPI file automatically. `openapi-typescript` turns it into TypeScript types. If a backend developer renames a field, **the frontend build fails** instead of the page silently showing `undefined`. This is the frontend half of NFR-MNT-005 (contract compatibility).

**Three chart libraries, each where it wins:**

| Chart | Library | Why |
|---|---|---|
| Monte Carlo fan chart (percentile bands of up to 10,000 paths) | ECharts | Canvas rendering handles large data; Recharts (SVG) slows down with many points. |
| Correlation heatmap (up to 500×500) | ECharts | Built-in heatmap with 250k cells on canvas. |
| Network graph (correlation network) | ECharts `graph` series | Force layout built in. |
| Persistence diagram / landscape | ECharts scatter/line | Many points; zoom and brush built in. |
| Candlesticks, replay, trade replay | Lightweight Charts | Made for financial candles and live-streamed updates; very small. |
| KPI sparkline, risk radar, contribution bars | Recharts (keep) | Small data, already written, simple API. |

**Zustand stays, but only for UI state.** Server data lives in TanStack Query. Keeping the two apart avoids stale copies of backend data in a global store.

### 2.3 Live updates in the browser

- **Alerts and job progress → Server-Sent Events (SSE)** using the browser's built-in `EventSource`. One-way, auto-reconnects, simple.
- **Replay controls (play/pause/speed) → WebSocket**, because the browser also sends commands.
- **Fallback:** if the connection drops for more than ~10 seconds, TanStack Query polls every 15 seconds until it reconnects (NFR-ACC-002).
- Both connect only to the **Dashboard service** through the gateway (ARC §7.3).

```ts
// src/services/live/useAlertStream.ts
useEffect(() => {
  const es = new EventSource('/v1/dashboard/stream/alerts', { withCredentials: true })
  es.addEventListener('alert', (e) => queryClient.invalidateQueries({ queryKey: ['alerts'] }))
  return () => es.close()
}, [])
```

### 2.4 What changes in the current POC code

| Current file/folder | Becomes |
|---|---|
| `src/services/mock/*` | `src/services/api/` (generated clients + hooks). Keep the mocks behind a `VITE_USE_MOCKS=true` flag for offline demos. |
| `src/demo/demoState.ts` | Removed; real job state comes from SSE + queries. |
| `src/demo/notifications.ts` | `src/services/live/useAlertStream.ts` |
| `src/demo/permissions.ts` | Reads the user's role from the JWT claims (display only; the **backend** enforces permissions). |
| `CandlestickChart.tsx` | Rewritten with Lightweight Charts |
| `MonteCarloFanChart.tsx`, `CorrelationHeatmap.tsx`, `NetworkGraph.tsx`, `PersistenceDiagram.tsx`, `PersistenceLandscape.tsx` | Rewritten with ECharts |
| `pages/auth/Login.tsx` | Real login + Cloudflare Turnstile (free bot check) |

### 2.5 Frontend authentication

- The access token (15 minutes) is kept **in memory**, not in `localStorage` (safer against script injection).
- The refresh token is an **HttpOnly, Secure, SameSite=Strict cookie** set by the Platform service.
- On page load the app calls `POST /v1/platform/auth/refresh` to get a new access token.

---

## 3. Backend: what we use and why

### 3.1 The exact backend stack (every service)

| Package | Used for | Why this one |
|---|---|---|
| **Python 3.12** | Language | See §4. |
| **uv** | Package and workspace manager | Very fast; one lockfile for a monorepo of 8 services + 1 shared lib. |
| **FastAPI** | HTTP API | Async, typed, generates OpenAPI (the per-service contract ARC §7.1 needs) for free. |
| **Uvicorn** | ASGI server | Standard FastAPI server. |
| **Pydantic v2** | Request/response/event validation | Rust core, fast; the same models produce OpenAPI and JSON Schema. |
| **pydantic-settings** | Config from environment | Twelve-factor config (NFR-MNT-001). |
| **SQLAlchemy 2.0 (async)** | Database access | Mature; supports the read/write-split repository pattern (ARC §8.8). |
| **asyncpg** | Postgres driver | Fastest async Postgres driver for Python. |
| **Alembic** | Migrations | One migration history per service (AD-17). |
| **Celery 5** | Background jobs | Retries, priorities, leases (visibility timeout), dead-letter queues, monitoring UI (Flower). |
| **confluent-kafka** | Publishing/consuming events | Official librdkafka binding, the fastest and most complete Kafka client for Python; works with Redpanda. |
| **httpx** | Service-to-service HTTP calls | Async, timeouts built in. |
| **stamina** | Retries with jitter | Small and correct defaults. |
| **aiobreaker** | Circuit breaker | Async circuit breaker for the resilience chain (ARC §7.5). |
| **PyJWT** + **cryptography** | Verify/issue EdDSA JWTs | Asymmetric tokens verified locally (ARC §9.1). |
| **structlog** | JSON logs with correlation id | Structured logs (NFR-OBS-002). |
| **opentelemetry-sdk** + instrumentations | Traces and metrics | Cross-service tracing (NFR-OBS-001). |
| **orjson** | Fast JSON | Faster event and API serialization. |
| **pytest**, **pytest-asyncio**, **testcontainers** | Tests | Real Postgres/Redis/Redpanda in tests. |
| **schemathesis** | API contract tests | Generates tests from OpenAPI (NFR-MNT-005). |
| **ruff**, **mypy** | Lint, format, type-check | Fast, one tool for lint + format. |

### 3.2 Why FastAPI (not Django or Flask)

| | FastAPI | Django (REST) | Flask |
|---|---|---|---|
| Async (many concurrent I/O calls) | ✅ native | Partial | ❌ mostly sync |
| Automatic OpenAPI contract | ✅ | Plugin | Plugin |
| Validation built in | ✅ Pydantic | Serializers | ❌ |
| Weight per service | Light | Heavy (ORM, admin, templates we don't need ×8) | Light |
| Fits "one small service per domain" | ✅ | ❌ designed for monoliths | ✅ but more DIY |

### 3.3 Why Celery for jobs (and why jobs aren't on Redpanda)

ARC §7.2 separates two different things:

- **A job** ("run this Monte Carlo") must be claimed by **one** worker, retried if the worker dies, and dead-lettered if it keeps failing. That's a **task queue** → Celery on Redis.
- **An event** ("simulation 42 completed") must be read by **many** services, in order, and replayable later. That's a **log** → Redpanda.

Celery settings that give us ARC §6's guarantees:

```python
celery_app.conf.update(
    task_acks_late=True,                # ack only after success → a crash re-queues the job
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,       # one heavy job at a time per process
    broker_transport_options={"visibility_timeout": 3600, "queue_order_strategy": "priority"},
    task_default_queue="simulation",
)
```

Idempotency: the job row has a unique `idempotency_key` (a hash of the parameters), so a double-click creates **one** run.

### 3.4 Why Redpanda instead of Apache Kafka

- It **speaks the Kafka protocol exactly**. Our code uses `confluent-kafka`; switching to Apache Kafka later is a hostname change.
- It is a **single native process with a built-in schema registry**. Kafka needs the JVM plus a separate schema registry (also JVM).
- Memory: Redpanda runs in about **1 GB** for dev. Kafka + schema registry usually need **2–3 GB**. Our free server has 12 GB for everything.
- AD-15's reason ("dev and prod must use the same broker semantics") still holds: partitions, offsets, consumer groups and `acks=all` behave the same.
- Licence: Redpanda Community is BSL, which only forbids **selling Redpanda as a hosted streaming service**. We don't.

---

## 4. Why not other languages

### 4.1 Backend: why Python and not…

The deciding fact: **QuantSim's hardest parts are maths, ML and topology**, and those libraries live in Python. GUDHI, giotto-ph, Ripser, persim, SHAP, hmmlearn, arch, scikit-learn, XGBoost, PyTorch and Hugging Face Transformers are all Python-first; most are C/C++ underneath, so they are fast. With 3 people, **one backend language** means anyone can fix any service (ARC §5.1: "learnable by three people").

| Language | What it's good at | Why not for QuantSim |
|---|---|---|
| **Go** | Small, fast web services; low memory | No mature persistent homology, SHAP, GARCH or financial NLP libraries. We'd need Python anyway for 4 of the 8 services, so two languages, two templates, two sets of tooling. |
| **Java / Kotlin (Spring Boot)** | Enterprise systems, strong typing | Each Spring service uses about 300–500 MB of RAM at idle. 16 JVM containers won't fit on a 12 GB free server. The ML/TDA ecosystem is weak. |
| **Node.js / TypeScript** | Same language as the frontend; I/O-heavy APIs | No NumPy/SciPy-level numeric ecosystem, no TDA libraries, one thread for CPU work. Monte Carlo and homology would be slow or need Python anyway. |
| **Rust** | Maximum speed and safety | Very slow to write for a student team, tiny quant/ML ecosystem, long compile times. The speed isn't needed: NumPy/Numba are already compiled. |
| **C++** | Raw performance | Too slow to develop and too easy to get memory bugs. We *already* use C++ indirectly: GUDHI and Ripser are C++ called from Python. |
| **Julia** | Scientific computing, very fast maths | Weak web-service ecosystem (no FastAPI equivalent), slow startup (JIT warm-up) per container, small community, few libraries for auth, Kafka, OpenTelemetry. |
| **R** | Statistics | Not built for web services, concurrency or production APIs. |
| **C# (.NET)** | Good all-rounder, fast | Same problem as Java/Go: the quant/TDA/SHAP ecosystem is in Python. |

**"Isn't Python slow?"** Not for this workload, because the heavy loops never run in pure Python:

- Monte Carlo → **NumPy** vectorized arrays (C) and **Numba** (compiles Python loops to machine code).
- Homology → **giotto-ph/GUDHI** (C++).
- Gradient boosting → **LightGBM/XGBoost** (C++).
- Neural nets → **PyTorch / ONNX Runtime** (C++).
- Data cleaning → **polars** (Rust).
- API waiting on the database/network → **async** FastAPI, where the language's speed barely matters.

**Escape hatch:** if profiling ever shows a pure-Python hotspot we can't vectorize, rewrite *that one function* in Rust with **PyO3/maturin** and call it from Python. No service rewrite.

### 4.2 Frontend: why TypeScript + React and not…

| Option | Why not |
|---|---|
| **Plain JavaScript** | No types; API field mistakes appear only at runtime in front of users. |
| **Next.js** | Needs a Node server (cost, second backend runtime) for server rendering we don't need. |
| **Angular** | Heavier, more boilerplate, and a full rewrite of the POC. |
| **Vue / Svelte** | Good frameworks, but a full rewrite of the POC for no real gain; fewer finance-chart wrappers. |
| **Streamlit / Dash / Gradio (Python UIs)** | Fine for notebooks and prototypes, but not for a multi-user product with roles, routing, live alerts and a custom design system. |
| **Flutter Web** | Large bundles, canvas-rendered text (poor accessibility), weak web charting ecosystem. |

---

## 5. Data and infrastructure

### 5.1 PostgreSQL 17 + TimescaleDB

**Why one engine for everything hot:** we need transactions and constraints (money, roles, invariants: ARC §8.9), JSON (registries: P5) **and** time series (bars, paths, portfolio values). TimescaleDB is a Postgres **extension**, so we get all of it with one backup tool, one driver and one set of skills.

**Why not the alternatives:**

| Alternative | Why not |
|---|---|
| MongoDB | No strong constraints, weak for money/transactions, and no time-series compression as good as Timescale's. |
| InfluxDB / QuestDB | Great for time series, but we'd still need Postgres for everything relational, so two databases to run and back up. |
| ClickHouse | Excellent analytics, but not a transactional database; a second system. |
| MySQL | No TimescaleDB, weaker JSONB, fewer constraint features. |
| Managed Postgres (Neon, Supabase) | Free tiers **can't load TimescaleDB**. Tiger Cloud (managed Timescale) has no free tier. So we self-host. |

**How the 8 databases are set up:**

```sql
-- one Postgres server, 8 databases, 8 login roles; each role can reach only its own database
CREATE ROLE market_svc LOGIN PASSWORD '...';
CREATE DATABASE market_db OWNER market_svc;
REVOKE CONNECT ON DATABASE market_db FROM PUBLIC;
-- repeat for platform, simulation, trading, ml, risk, xai, dashboard
```

This enforces P8 ("a service owns its data") **by permission, not by convention**: `market_svc` physically can't read `trading_db`.

**Standard rules for every table** (ARC §8.3, §8.9):
- IDs: **UUID v7** (time-ordered). Generate in Python with the `uuid-utils` package.
- Timestamps: `timestamptz`, always UTC.
- Money/prices: `NUMERIC(23,8)` stored, `NUMERIC(28,12)` in calculations. **Never `float`.**
- Every database has `outbox_event`, `processed_event` and `audit.change_log` (from the template).

**Hypertable example:**

```sql
CREATE TABLE market.bar (
  instrument_id uuid NOT NULL,
  ts            timestamptz NOT NULL,
  open  NUMERIC(23,8) NOT NULL, high NUMERIC(23,8) NOT NULL,
  low   NUMERIC(23,8) NOT NULL, close NUMERIC(23,8) NOT NULL,
  volume NUMERIC(28,4) NOT NULL,
  ingestion_run_id uuid NOT NULL,
  PRIMARY KEY (instrument_id, ts)          -- re-ingesting the same window can't duplicate (FR-MKT-002)
);
SELECT create_hypertable('market.bar', by_range('ts', INTERVAL '7 days'));
ALTER TABLE market.bar SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_id');
SELECT add_compression_policy('market.bar', INTERVAL '30 days');
```

**PgBouncer:** one PgBouncer container in transaction-pooling mode with an entry per database. Services connect to PgBouncer, never straight to Postgres. (asyncpg needs `statement_cache_size=0` behind transaction pooling.)

**Backups:** **pgBackRest**, a weekly full + 6-hourly incremental backup, with continuous WAL archiving to R2 (NFR-REL-002).

### 5.2 Redis 8: two instances

| Instance | Memory policy | Persistence | Holds |
|---|---|---|---|
| `redis-cache` | `allkeys-lru` (evict when full) | none | Cached API responses, dashboard tiles, pub/sub for SSE fan-out, rate-limit counters |
| `redis-queue` | `noeviction` (never evict) | AOF every second | Celery queues, job progress |

**Why two:** if one Redis held both, memory pressure could **silently evict a queued simulation job**. Different data needs opposite settings.

**Per-service ownership inside Redis:** each service gets its own **logical DB number** and its own **ACL user** restricted to that DB's key prefix, so services can't read each other's cache.

**Why Redis, not Valkey:** Redis 8 is AGPLv3 (open source again). We use it unmodified and internally, so AGPL imposes nothing. Valkey is a drop-in replacement if a customer ever bans AGPL.

### 5.3 Object storage: Cloudflare R2 (cloud) and SeaweedFS (local)

- **R2:** S3-compatible, 10 GB free, **no egress fees**.
- **Local dev:** SeaweedFS (S3-compatible, Apache-2.0). **Why not MinIO:** MinIO's community edition stopped publishing images and moved to maintenance mode in 2025.
- Python access: **boto3** (or `aioboto3` in async code) with the endpoint URL set per environment.
- **One bucket per purpose, one prefix + credential per service:** `quantsim-runs/simulation/...`, `quantsim-models/ml/...`, `quantsim-exports/dashboard/...`.
- File format for archives: **Parquet with zstd compression**, written by **polars** or **pyarrow**.

### 5.4 Redpanda (event backbone)

**Topics** (partition key in brackets):

| Topic | Key | Producer | Main consumers |
|---|---|---|---|
| `platform.user` (`user.deactivated`, `role.changed`) | user_id | M0 | all |
| `platform.audit` (`audit.recorded`) | service | all | M0 |
| `market.instrument` (`instrument.created/retired`) | instrument_id | M1 | M2, M3, M5 |
| `market.bar` (`bar.ingested`) | instrument_id | M1 | M4 |
| `market.news` (`news.ingested`) | article_id | M1 | M4 |
| `market.tick` | instrument_id | M1 (replay) | M3 |
| `simulation.run` (`sim.progress`, `sim.completed`, `sim.failed`) | run_id | M2 | M3, M5, M7 |
| `trading.portfolio` (`portfolio.*`, `fill.*`) | portfolio_id | M3 | M4, M5, M7 |
| `ml.prediction` (`prediction.ready`, `model.registered`) | entity_id | M4 | M5, M6, M7 |
| `risk.result` (`stress.completed`, `stress.failed`, `regime.transition`, `risk.threshold.breached`, `risk.composite.updated`) | portfolio_id / basket_id | M5 | M6, M7 |
| `xai.explanation` (`explanation.ready`) | subject_id | M6 | M7 |
| `dashboard.alert` (`alert.triggered`) | user_id | M7 | M7 |

**Every event has the same envelope:**

```json
{
  "event_id": "0192f3c1-...",          // UUID v7, used for de-duplication
  "event_type": "sim.completed",
  "schema_version": 1,
  "occurred_at": "2026-11-03T10:22:11Z",
  "producer": "simulation",
  "correlation_id": "…",               // same id across the whole user action
  "traceparent": "00-…",               // OpenTelemetry trace context
  "payload": { "run_id": "…", "instrument_id": "…", "var_95": "-0.0412" }
}
```

Schemas are **JSON Schema files in `contracts/events/`**, registered in Redpanda's schema registry by CI. Rule: **add fields only**; breaking changes need a new `schema_version`.

**Production settings:** 3 brokers, replication factor 3, `min.insync.replicas=2`, producer `acks=all`, `enable.idempotence=true` (NFR-REL-004).

### 5.5 Gateway, containers, secrets

- **Traefik v3** reads routing from Docker/Kubernetes labels. **Why not Kong:** Kong needs more memory and its own configuration database or declarative setup; Traefik is ~50 MB.
- **Docker Compose** for dev and the demo, with **profiles** so a laptop can start only a slice: `core` (gateway, platform, market, dashboard, infra), `sim`, `trading`, `risk`, `ml`, `full`.
- **k3s** for production Kubernetes: certified Kubernetes in ~500 MB, so the same manifests work on a full cluster later.
- **SOPS + age** for secrets in early phases: secrets live encrypted in git and are decrypted at deploy time. Nothing runs in memory. **OpenBao** (the open-source fork of HashiCorp Vault) replaces it when per-service dynamic database passwords are worth running a server (ARC §9.3).
- **OpenTofu** (open-source Terraform fork) for servers, DNS, R2 buckets.

---

## 6. The shared service template

ARC §5.1: "eight services built eight different ways would be unmaintainable by three people." We build **one Python package, `qs_template`**, and every service imports it. Only the domain code differs.

### 6.1 Folder layout of every service

```
services/<name>/
├─ app/
│  ├─ api/            # Layer 1: FastAPI routers, request/response models, RBAC declarations
│  ├─ application/    # Layer 2: use cases ("start a simulation run"), transactions
│  ├─ domain/         # Layer 3: pure business logic and maths (no I/O, easy to unit-test)
│  ├─ infrastructure/ # Layer 4: repositories (DB), outbound HTTP clients, event publishers, object store
│  ├─ consumers/      # Event handlers (Redpanda)
│  ├─ worker/         # Celery tasks (if this service has a worker)
│  └─ main.py         # builds the FastAPI app via qs_template.create_app(...)
├─ alembic/           # this service's own migration history
├─ tests/
├─ Dockerfile         # same base image for all services
└─ pyproject.toml
```

Rule (ARC §4.2): **only Layer 4 talks to the outside world.** Domain code never opens an HTTP connection or publishes to Redpanda directly.

### 6.2 What `qs_template` provides

| Piece | What it does | Built with |
|---|---|---|
| `create_app()` | FastAPI app with `/healthz`, `/readyz`, CORS off (gateway only), error handlers | FastAPI |
| Settings | Reads config from env/secret files | pydantic-settings |
| Logging | JSON logs with `correlation_id`, `user_id`, `service` on every line | structlog |
| Tracing | Auto-traces HTTP, SQL, Redis, Celery, Kafka; propagates `traceparent` into event headers | OpenTelemetry |
| Auth | Verifies EdDSA JWT against cached JWKS; checks local denylist | PyJWT |
| RBAC | `require_role("quant")` dependency + mandatory row-scope filter in repositories | FastAPI dependencies |
| DB session | Async engine, read/write session split, sets `app.actor_id` for audit triggers | SQLAlchemy |
| Outbox | `outbox.add(topic, key, payload)` in the same transaction + drain worker | SQLAlchemy + confluent-kafka |
| Consumer | Idempotent consumer loop with `processed_event` de-duplication and manual offset commit | confluent-kafka |
| Resilient client | Timeout (2 s reads / 5 s bulk), 2 retries with jitter, circuit breaker, bulkhead, **named fallback required** | httpx + stamina + aiobreaker |
| Jobs | Base Celery task with job-row state machine, idempotency key, progress publishing | Celery |
| Audit | Alembic helper that installs the generic audit trigger on a table | SQL |
| Migrations | Alembic env configured for the service's own database | Alembic |

### 6.3 The outbox, simply

**Problem:** we save a row, then publish an event. If the process crashes between the two, other services never hear about it.

**Fix:** write the event into an `outbox_event` table **in the same database transaction** as the business row. A small background loop publishes it afterwards.

```python
# application layer (inside one transaction)
async with uow.begin():
    run = await runs.add(SimulationRun(...))
    await uow.outbox.add(topic="simulation.run", key=str(run.id),
                         event_type="sim.completed", payload={...})
# both rows commit together, or neither does
```

```sql
-- drain loop (runs every ~200 ms in each service)
SELECT id, topic, event_key, payload FROM outbox_event
WHERE published_at IS NULL ORDER BY id LIMIT 500
FOR UPDATE SKIP LOCKED;
-- publish each to Redpanda, wait for the ack, then:
UPDATE outbox_event SET published_at = now() WHERE id = ANY(:ids);
```

A crash after publishing but before the `UPDATE` causes a **duplicate**, never a loss. Consumers handle duplicates:

```python
async def handle(event):
    async with uow.begin():
        inserted = await uow.execute(
            "INSERT INTO processed_event(event_id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING 1",
            {"id": event.event_id})
        if not inserted:
            return            # already handled, so do nothing
        await apply_business_change(event)
    consumer.commit(message)  # commit the offset only after the DB commit
```

### 6.4 The audit trigger (every service)

```sql
CREATE FUNCTION audit.log_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO audit.change_log(table_name, op, row_pk, before, after, actor_id)
  VALUES (TG_TABLE_NAME, left(TG_OP,1),
          COALESCE(NEW.id, OLD.id)::text,
          CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
          CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END,
          nullif(current_setting('app.actor_id', true), '')::uuid);
  RETURN NULL;
END $$;
-- enabled per table:
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON trading.portfolio
FOR EACH ROW EXECUTE FUNCTION audit.log_change();
```

The template sets `SET LOCAL app.actor_id = '<user id>'` at the start of each transaction. Because `before` is kept on DELETE, deleted rows stay queryable (FR-PLT-007).

---

## 7. Module-by-module implementation

Each module below follows the same format: **what it does → libraries → how it works → data → events → API → watch-outs.**

---

### M0 · Platform / Identity

**What it does (simply):** logins, users, roles, who can see which portfolios, and a searchable index of audit changes across all services. It **issues** the tokens; every other service only **checks** them.

**Libraries**

| Library | Used for |
|---|---|
| `argon2-cffi` | Password hashing (Argon2id), NFR-SEC-004 |
| `PyJWT` + `cryptography` | Signing access tokens with **EdDSA (Ed25519)** |
| `Authlib` | Optional "Sign in with GitHub" (OAuth) |
| `httpx` | Verifying Cloudflare Turnstile tokens at signup |
| `resend` (Python SDK) | Verification and password-reset emails |

**How it works**

1. **Login:** `POST /v1/platform/auth/login` → look up the user → `argon2.verify()` → create:
   - an **access token** (JWT, 15 min): `sub`, `role`, `scopes` (coarse portfolio/instrument grants), `jti`, `exp`
   - a **refresh token**: a random 256-bit string, stored **hashed** in `platform.refresh_token`, sent as an HttpOnly cookie.
2. **Publishing the public key:** `GET /.well-known/jwks.json` returns the Ed25519 public key(s). Other services cache it for 10 minutes. Key rotation: publish the new key, wait one cache period, then start signing with it.
3. **Refresh:** `POST /auth/refresh` checks the stored refresh-token hash, **rotates** it (old one is invalidated), and refuses deactivated users (FR-PLT-002).
4. **Deactivate / role change:** the update and an outbox event (`user.deactivated` / `role.changed`) are written in one transaction. Every service consumes it into a small **local denylist** (Redis set with TTL = access-token lifetime), which the template checks on each request.
5. **Audit index:** consumes `audit.recorded` from all services into `platform.audit_index(service, table, row_pk, op, actor_id, changed_at, correlation_id)`. The Audit Log page reads this. For the full before/after, it calls the owning service's `GET /v1/<svc>/audit/{row_pk}`.

**Data (`platform_db`)**

```sql
CREATE TYPE user_role AS ENUM ('admin','quant','analyst','viewer');   -- NFR-INT-002
CREATE TABLE platform.app_user (id uuid PRIMARY KEY, username text UNIQUE NOT NULL,
  email citext UNIQUE NOT NULL, password_hash text NOT NULL, role user_role NOT NULL,
  is_active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz);
CREATE TABLE platform.refresh_token (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform.app_user,
  token_hash bytea NOT NULL, expires_at timestamptz NOT NULL, revoked_at timestamptz);
CREATE TABLE platform.scope_grant (user_id uuid, resource_type text CHECK (resource_type IN ('portfolio','instrument')),
  resource_id uuid, PRIMARY KEY (user_id, resource_type, resource_id));
```

**API:** `/auth/login`, `/auth/refresh`, `/auth/logout`, `/users` (admin CRUD), `/users/{id}/role`, `/users/{id}/deactivate`, `/scope-grants`, `/audit-index`, `/.well-known/jwks.json`

**Frontend pages:** Login, Admin → Users, Roles, System; Audit Log.

**Watch-outs:** never put the private signing key anywhere except M0's secrets. Rate-limit `/auth/login` per IP and per username (Redis counter) to stop password guessing.

---

### M1 · Market Data

**What it does (simply):** downloads prices and news, **cleans them before anyone else sees them**, computes returns/volatility/correlations once, and runs "replay" sessions that play history back like a live market.

**Libraries**

| Library | Used for |
|---|---|
| `httpx` | Calling data vendors |
| `polars` | Fast cleaning and return/volatility calculations |
| `pandera[polars]` | Declarative data-quality rules → the cleaning gate and its report |
| `exchange_calendars` | Knowing trading days, so a holiday isn't flagged as a missing bar |
| `numpy` | Correlation matrices |
| `rapidfuzz` | Fuzzy matching company names in news to instruments |
| `spaCy` (`en_core_web_sm`) | Finding company/organization names in news text |
| `trafilatura` | Stripping boilerplate from news article HTML |
| `ftfy` | Fixing broken text encoding in news |
| `celery` (beat) | Scheduled ingestion |
| `xxhash` | Fast fingerprints of correlation matrices (ARC §5.4) |

**How ingestion works (FR-MKT-002, FR-MKT-011)**

```
Celery beat (daily 22:30 UTC)
  └─ ingest_bars(source="tiingo", window)
       1. create ingestion_run row (status=running)
       2. fetch raw JSON from vendor → INSERT into market.staging_bar (raw, untouched)
       3. CLEANING GATE (pandera rules on a polars DataFrame):
            • timestamps converted to UTC
            • missing bars: compare against exchange_calendars sessions
            • duplicate bars: same (instrument, ts)
            • price checks: open/high/low/close > 0, low ≤ open,close ≤ high
            • outliers: |daily return| > 50% → flag for review
            • zero-volume on a trading day → flag
       4. rows that pass → INSERT … ON CONFLICT (instrument_id, ts) DO NOTHING into market.bar
          rows that fail → market.rejected_bar (kept, with the reason)
       5. write reconciliation report JSON on the ingestion_run (passed / corrected / rejected counts)
       6. compute returns + rolling volatility for affected instruments → market.return_series
       7. outbox: bar.ingested (one per instrument/window, not per bar)
       8. ingestion_run status=succeeded
```

```python
# domain/cleaning.py (sketch)
bar_schema = pa.DataFrameSchema({
    "open":  pa.Column(float, pa.Check.gt(0)),
    "high":  pa.Column(float, pa.Check.gt(0)),
    "low":   pa.Column(float, pa.Check.gt(0)),
    "close": pa.Column(float, pa.Check.gt(0)),
    "volume": pa.Column(float, pa.Check.ge(0)),
}, checks=[pa.Check(lambda df: (df["low"] <= df["high"]), name="low_le_high")])
# lazy=True collects every failure → becomes the rejected rows + report
```

**Returns & volatility (FR-MKT-003):** log return `r_t = ln(P_t / P_{t-1})`; 20-day and 60-day rolling volatility `std(r) × √252`. Stored once in a hypertable and published, so no other service recomputes them.

**Correlation matrices (FR-MKT-004, AD-19)**

- `POST /v1/market/correlations/rolling` with `{basket_id, start, end, window: 60, step: 5}` returns **all** matrices in one response.
- Computed with `numpy.corrcoef` on the aligned return matrix.
- A closed historical window never changes, so each matrix is stored once in `market.correlation_matrix` with a **fingerprint** `xxh3(basket, window bounds, row count, data)`. Responses carry `ETag` and long cache headers.
- Transfer format: `application/vnd.apache.arrow.stream` (Arrow IPC via `pyarrow`) for big requests, JSON for small ones. (This is the "bulk path" ARC §7.1 reserved gRPC for; Arrow-over-HTTP gives the same benefit with no extra toolchain.)

**News (FR-MKT-006, FR-MKT-011)**

1. Fetch from Finnhub (already has tickers), GDELT (broad), and SEC EDGAR 8-K filings.
2. Clean: `ftfy` for encoding, `trafilatura` for boilerplate, dedupe by a hash of the normalized title + source.
3. Link to instruments: vendor tickers first; otherwise spaCy finds organization names → `rapidfuzz` matches them to the instrument master's names/aliases (score ≥ 90).
4. Store in `market.news_article` + `market.news_instrument_link`; publish `news.ingested`.

**Replay sessions (FR-MKT-007/008/009)**

- `market.replay_session` has `CHECK (end_time > start_time)` (FR-MKT-008).
- A replay worker reads bars (or real crypto ticks from Binance dumps) in time order and publishes them to `market.tick`, keyed by instrument, at `speed ×` real time.
- Controls (play/pause/speed) arrive through M7's WebSocket → M7 calls `POST /v1/market/replay-sessions/{id}/control` → the worker reads the new state from Redis on each tick.
- **Common market-environment interface (FR-MKT-009):** replay sessions and simulation runs both expose the same tick event shape `{env_id, env_type: "replay"|"synthetic", instrument_id, ts, price, volume}`, so Trading doesn't care which one it's bound to.

**Corporate actions (FR-MKT-010, Extended):** Tiingo EOD returns `splitFactor` and `divCash`. Store both raw and adjusted series; returns use adjusted prices. (Recommended answer to the open question in ARC §15: **store both**.)

**Sector/geography data:** SEC EDGAR `submissions` API gives SIC industry code and state/country, stored on the instrument, used by M5 breakdowns (FR-RSK-008).

**Data (`market_db`):** `instrument`, `instrument_alias`, `basket`, `basket_member` (with `valid_from/valid_to` for history), `staging_bar`, `bar` (hypertable), `rejected_bar`, `ingestion_run`, `return_series` (hypertable), `correlation_matrix`, `corporate_action`, `news_article`, `news_instrument_link`, `replay_session`.

**Events out:** `instrument.created`, `instrument.retired`, `bar.ingested`, `news.ingested`, `tick.*`, `replay.*`

**Frontend pages:** Market Environments, Market Data, Instruments, Replay.

**Watch-outs:** free data plans are for **non-commercial use**; switch to a paid licence before charging users. Always send the `User-Agent` header EDGAR requires, and stay under 10 requests/second.

---

### M2 · Simulation

**What it does (simply):** learns how a stock behaves (calibration), then generates thousands of possible futures (Monte Carlo) and summarizes the risk (mean, VaR, CVaR).

**Libraries**

| Library | Used for |
|---|---|
| `numpy` | Vectorized path generation; `SeedSequence` for reproducible parallel random numbers |
| `numba` | Compiling loops that can't be vectorized (jumps, regime switching) |
| `scipy.optimize` / `scipy.stats` | Maximum-likelihood calibration |
| `hmmlearn` | Regime-switching calibration (Gaussian Hidden Markov Model) |
| `polars` / `pyarrow` | Writing path quantiles to Parquet |
| `celery` | Running jobs on CPU workers |

**Calibration (FR-SIM-001 to 005)**

1. `POST /v1/simulation/calibrations {instrument_id, model, start, end}`
2. Fetch prices from M1 (resilient client). Store the **input fingerprint** (instrument, range, row count, hash).
3. Fit the model on log returns `r` with time step `Δt = 1/252`:

| Model | Parameters | How we fit |
|---|---|---|
| **GBM** | drift μ, volatility σ | Closed form: `σ = std(r)/√Δt`, `μ = mean(r)/Δt + σ²/2` |
| **Ornstein–Uhlenbeck** (mean reversion) | speed κ, long-run mean θ, volatility σ | Regress `x_{t+1}` on `x_t` (AR(1)) → convert: `κ = −ln(b)/Δt`, `θ = a/(1−b)`, σ from residuals |
| **Merton jump-diffusion** | μ, σ, jump rate λ, jump mean μ_J, jump size σ_J | `scipy.optimize.minimize` on the negative log-likelihood (a Poisson mixture of normals, truncated at ~10 jumps per step) |
| **Regime switching** (Extended) | per-regime μ_k, σ_k, transition matrix P | `hmmlearn.hmm.GaussianHMM(n_components=2 or 3).fit(r)` |

4. Save `simulation.calibration(model_type, params jsonb, fit_stats jsonb, input_fingerprint)`.

**Monte Carlo run (FR-SIM-006 to 009)**

1. `POST /v1/simulation/runs {calibration_id, instrument_id, n_paths, n_steps, seed?}`
2. The API checks the plan's limits (e.g. Free: 10,000 paths), creates `simulation.run` (status `queued`, unique `idempotency_key`), enqueues a Celery task, returns `202 {run_id}` in < 800 ms (NFR-PERF-004).
3. **The database blocks a mismatched instrument (FR-SIM-007):**

```sql
ALTER TABLE simulation.calibration ADD CONSTRAINT calib_id_instr UNIQUE (id, instrument_id);
ALTER TABLE simulation.run ADD CONSTRAINT run_matches_calibration
  FOREIGN KEY (calibration_id, instrument_id) REFERENCES simulation.calibration (id, instrument_id);
```

4. The worker splits the paths into **shards** (e.g. 8 × 1,250) with independent random streams, runs them in parallel with a Celery `group`, and merges the results (NFR-SCAL-004):

```python
# domain/models/gbm.py (vectorized, no Python loop over paths)
def simulate_gbm(s0, mu, sigma, n_paths, n_steps, dt, rng):
    z = rng.standard_normal((n_paths, n_steps))
    log_inc = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    return s0 * np.exp(np.cumsum(log_inc, axis=1))

# seeds: reproducible and independent per shard
children = np.random.SeedSequence(run.seed).spawn(n_shards)
rngs = [np.random.default_rng(s) for s in children]
```

```python
# domain/models/ou.py (exact discretization, loop compiled by Numba)
@numba.njit(parallel=True)
def simulate_ou(x0, kappa, theta, sigma, n_paths, n_steps, dt, z):
    out = np.empty((n_paths, n_steps))
    e = np.exp(-kappa * dt); sd = sigma * np.sqrt((1 - e**2) / (2 * kappa))
    for p in numba.prange(n_paths):
        x = x0
        for t in range(n_steps):
            x = theta + (x - theta) * e + sd * z[p, t]
            out[p, t] = x
    return out
```

   - **Jump-diffusion:** GBM increments + `rng.poisson(λΔt)` jump counts × `normal(μ_J, σ_J)` jump sizes.
   - **Regime switching:** simulate the Markov chain of regimes per path (Numba), then pick μ/σ per step from the current regime.

5. **Statistics (FR-SIM-008):** terminal price mean; returns `R = S_T/S_0 − 1`; `VaR_95 = −quantile(R, 0.05)`; `CVaR_95 = −mean(R[R ≤ quantile(R, 0.05)])`. Stored as `NUMERIC`.
6. **Storing paths** (see change C2 in §13):
   - Small runs (≤ 1,000 paths × 252 steps): every value into `simulation.path_value` (hypertable, space-partitioned by `run_id`), written with **asyncpg `copy_records_to_table`** (much faster than INSERTs).
   - Large runs: store **seed + config + per-step percentiles (1, 5, 25, 50, 75, 95, 99)** as Parquet in R2. Any path can be regenerated exactly from the seed.
7. Publish `sim.progress` every ~10% and `sim.completed` (or `sim.failed`) via the outbox.

**Data (`simulation_db`):** `calibration`, `run`, `run_statistics`, `path_value` (hypertable), `path_quantile`, `job`, `instrument_ref` (local projection from `instrument.*` events).

**Frontend pages:** Simulations, Configure/Run Simulation, Simulation Results (fan chart), Calibrations, Models.

**Watch-outs:** set `OMP_NUM_THREADS=1` in workers when running shards in parallel, so NumPy threads don't fight each other. Reserve one CPU core for the API.

---

### M3 · Trading

**What it does (simply):** plays a strategy against a market (replayed or simulated) one tick at a time, places and fills orders with realistic costs, and records **every single event forever** so a portfolio's history can be replayed exactly.

**Libraries**

| Library | Used for |
|---|---|
| Python `decimal` (context precision 28) | All money arithmetic, never `float` (NFR-INT-001) |
| `confluent-kafka` | Consuming ticks per partition, in order |
| `pydantic` | Typed event payloads (`OrderPlaced`, `OrderFilled`, …) |
| `quantstats` or `empyrical-reloaded` | Portfolio statistics for display (Sharpe, drawdown); M4 owns the official metrics |
| `RestrictedPython` (optional) | If strategies are user-written code, sandbox them; otherwise use parameterized built-in strategies |

**Strategies (FR-TRD-001).** Start with **built-in, parameterized strategies** (safe and simple): moving-average crossover, mean reversion (z-score), momentum, buy-and-hold, and "ML signal with rule-based fallback" (ARC §5.2). A strategy is a Python class with one method:

```python
class Strategy(Protocol):
    def on_tick(self, tick: Tick, state: PortfolioState) -> list[OrderIntent]: ...
```

`trading.strategy` stores `{kind: "ma_crossover", params: {"fast": 20, "slow": 50}}` as JSONB.

**How the engine works**

```
market.tick (partitioned by instrument) ─┐
sim.completed → replay simulated paths ──┼──► engine worker (one consumer per partition)
                                         │
for each tick, for each portfolio bound to this environment:
   1. append TICK event
   2. match resting orders:
        limit buy  fills if price ≤ limit;  stop buy fills (as market) if price ≥ stop
        stop-limit becomes a limit order when the stop triggers
   3. strategy.on_tick() → new order intents → append ORDER_PLACED
   4. market orders fill at: price × (1 ± slippage)
        slippage models: fixed bps | volume-based (bps × order_qty / bar_volume)
   5. cost = fixed + per_share × qty + pct × notional (tiered model = Extended)
   6. append ORDER_FILLED (fill price, qty, cost), update projections
   7. outbox: fill.executed, portfolio.updated
```

**The event log (FR-TRD-006), with no gaps and strictly ordered:**

```sql
CREATE TABLE trading.trade_event (
  portfolio_id uuid NOT NULL, seq bigint NOT NULL, event_time timestamptz NOT NULL,
  event_type text NOT NULL, payload jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (portfolio_id, seq, event_time));
SELECT create_hypertable('trading.trade_event', by_range('event_time'));
REVOKE UPDATE, DELETE ON trading.trade_event FROM trading_svc;   -- append-only (NFR-INT-005)
```

How `seq` stays gap-free: each portfolio has a row in `trading.portfolio_state_current` with `last_seq`. The engine does `SELECT … FOR UPDATE` on it, writes `seq = last_seq + 1`, and updates `last_seq`, all in one transaction. The Kafka partition key guarantees only one consumer handles a given instrument at a time.

**Projections (FR-TRD-007/008):** `holding_history` (append-only), `portfolio_value` (hypertable: value, cash, P&L), `portfolio_state_current` (small cache). A **rebuild command** replays the log from `seq = 1` into empty projections, and a test asserts the rebuilt state equals the live state.

**Point-in-time state for other services:** `GET /v1/trading/portfolios/{id}/state?as_of=2026-10-01T00:00:00Z`.

**Data (`trading_db`):** `strategy`, `portfolio` (starting capital, base currency, `env_type`, `env_id`), `order`, `fill`, `trade_event`, `holding_history`, `portfolio_value`, `portfolio_state_current`, `instrument_ref`.

**Frontend pages:** Strategies, Configure Strategy, Portfolios, Create Portfolio, Trade Replay.

**Watch-outs:** never scale by adding consumers to the same partition (ordering breaks). Scale by adding partitions. Use `Decimal` everywhere in the domain layer; convert to float **only** when sending to charts.

---

### M4 · Machine Learning

**What it does (simply):** reads news and prices and makes predictions (sentiment, future volatility, regime, drawdown risk, portfolio health, strategy metrics). Every prediction records exactly which model version made it, and models can **never see data from the future**.

**Libraries**

| Library | Used for | Requirement |
|---|---|---|
| `transformers` + `ProsusAI/finbert` | Financial sentiment | FR-ML-004 |
| `optimum` + `onnxruntime` | Export FinBERT to ONNX → fast CPU inference, ~300 MB instead of 1.5 GB+ with PyTorch | FR-ML-004 |
| `gliner` | Zero-shot extraction of entities (company, amount, person) from news | FR-ML-007 |
| `scikit-learn` | Pipelines, metrics, baselines (Random Forest) | FR-ML-008/009/010 |
| `lightgbm` / `xgboost` | Tabular models (regime, drawdown, health) | FR-ML-008/009/010 |
| `arch` | GARCH(1,1) volatility forecasts (baseline) | FR-ML-005 |
| `torch` (training only) | LSTM volatility challenger | FR-ML-005 |
| `mlflow` | Experiment tracking + artifact storage in R2 | FR-ML-001/003 |
| `optuna` | Hyperparameter search | – |
| `quantstats` / `numpy` | Sharpe, win rate, alpha, beta | FR-ML-006 |
| `statsmodels` | Alpha/beta regression against a market index | FR-ML-006 |

**The point-in-time feature store (FR-ML-002)**

M4 is **not allowed** to read other services' databases. It builds its own features from events:

```
bar.ingested   → returns, rolling vol (5/20/60d), momentum, RSI, drawdown-from-peak
news.ingested  → sentiment score (after FinBERT), news count per instrument per day
portfolio.*    → exposure, concentration, cash ratio
FRED (VIX, 3-month T-bill) → macro features
Market Data correlation series → average pairwise correlation, its 20-day change
```

Each value is saved with **two times**: `event_time` (the day it describes) and `knowledge_time` (when M4 received it). The *only* way to read features is an as-of query:

```sql
-- latest known value of each feature, as it was known at :t
SELECT DISTINCT ON (feature_name) feature_name, value
FROM ml.feature_value
WHERE entity_id = :entity AND event_time <= :t AND knowledge_time <= :t
ORDER BY feature_name, event_time DESC, knowledge_time DESC;
```

To train with no look-ahead, labels are built from the **future** window (e.g. max drawdown over the next 20 days), but features only as of `t`. Train/test split uses **walk-forward** (`sklearn.model_selection.TimeSeriesSplit` with a gap equal to the label horizon), never a random shuffle.

**Each task**

| Task | Model(s) | Input | Output stored |
|---|---|---|---|
| **Sentiment** (Core) | FinBERT (ONNX) | Article title + first 512 tokens | `{positive, neutral, negative}` probabilities + score = P(pos) − P(neg) |
| **Volatility forecast** (Core) | GARCH(1,1) baseline → LSTM challenger | 2 years of daily returns | Forecast annualized vol for 1, 5, 20 days |
| **Strategy metrics** (Core) | Deterministic maths | `portfolio_value` projection + index returns + risk-free rate (FRED) | Sharpe = mean(excess)/std × √252; win rate = winning closed trades / all; alpha/beta from an OLS regression on index returns |
| **Event extraction** (Extended) | GLiNER entities + LightGBM text classifier trained on **SEC 8-K item codes** as labels | News/filing text | `{event_type: "layoffs", company, amount, date}` |
| **Regime classification** (Extended) | LightGBM | Vol, correlation change, VIX, momentum | `calm / trending / stressed` + probabilities |
| **Drawdown risk** (Extended) | LightGBM classifier (label: next-20-day drawdown > 10%) | Portfolio + market features | Probability 0–1 |
| **Portfolio health** (Extended) | Weighted score of drawdown prob, vol forecast, concentration, Sharpe | Other predictions | 0–100 + breakdown |

GARCH example:

```python
from arch import arch_model
am = arch_model(returns_pct, vol="GARCH", p=1, q=1, dist="t")
res = am.fit(disp="off")
var_forecast = res.forecast(horizon=20).variance.iloc[-1]    # daily variances, in %²
annual_vol = np.sqrt(var_forecast.mean() * 252) / 100
```

**Model registry (FR-ML-001/003)**

- `ml.model` (task type as a **registry value**, not an enum, NFR-SCAL-003), `ml.model_version` (hyperparameters, metrics, `artifact_uri`, `status: staging|production|archived`), `ml.training_run` (loss curve, metrics, status).
- MLflow tracks experiments. Its backend store is a separate schema in `ml_db`; artifacts go to `r2://quantsim-models/ml/…`. Our own tables stay the source of truth for "which version is live".
- Every row in `ml.prediction` has `model_version_id` + `feature_snapshot_id` (the exact frozen feature vector), which M6 needs for SHAP.

**Where GPUs come from (for free):** training FinBERT fine-tunes or LSTMs runs in **Kaggle Notebooks or Google Colab** (free GPUs), which log to our MLflow server. Production inference runs on **CPU** (ONNX, LightGBM, GARCH), so the platform needs **no GPU server**.

**Serving:** cheap single predictions on the API tier (`POST /v1/ml/predict/{task}`); batch jobs (score all news from today, nightly vol forecasts) on the Celery worker. Publishes `prediction.ready`.

**Explanation bundle for M6:** `GET /v1/ml/predictions/{id}/explanation-bundle` → `{artifact_uri, model_family, feature_names, feature_vector, background_sample_uri}`.

**Data (`ml_db`):** `model`, `model_version`, `training_run`, `feature_definition`, `feature_value` (hypertable), `feature_snapshot`, `prediction` (hypertable), `extracted_event`, `job`.

**Frontend pages:** ML Models, Predictions, Features, News Extraction.

**Watch-outs:** FinBERT truncates at 512 tokens; score the headline + lead paragraph. Retrain on a schedule and compare the challenger with the production model before promoting it.

---

### M5 · Risk & TDA

**What it does (simply):** two things. (1) **Stress testing:** "what happens to my portfolio in a flash crash?" (2) **Topological Data Analysis:** looks at the *shape* of how stocks move together to spot the market becoming fragile before a crash. It also computes the **composite risk score** shown on the Risk Hub page.

**Libraries**

| Library | Used for |
|---|---|
| `numpy`, `scipy` | Shocks, VaR, drawdowns |
| **`giotto-ph`** (`gph.ripser_parallel`) | Fast multi-threaded persistent homology (Vietoris–Rips) |
| **`gudhi`** | Sparse Rips / witness complexes for large baskets (> 300 assets); cross-checks |
| **`persim`** | Persistence landscapes, bottleneck/Wasserstein distances |
| `networkx` | Correlation network for the Network Graph view |
| `polars` | Attribution and breakdown tables |

#### Part 1: Stress testing (FR-RSK-001 to 009, 018)

**Scenario catalog is data, not code (FR-RSK-001):**

```json
{ "code": "flash_crash", "type": "price_shock",
  "params": { "shock_pct": -0.12, "duration_steps": 1, "recovery_half_life_days": 15,
              "applies_to": "all", "vol_multiplier": 2.5 } }
```

Five built-in scenario types, each a small Python "shock function" registered by `type`:

| Scenario | How it's applied |
|---|---|
| Flash crash | Instant price drop on all assets, then a recovery curve |
| Volatility spike | Multiply σ by k for N days and re-simulate paths (via M2's calibration) |
| Liquidity shock | Increase slippage and spreads × k; partial fills |
| Sector collapse | Drop only assets in a SIC sector (from M1 reference data) |
| Correlated-asset failure | Push the correlation matrix toward 1 (`ρ' = ρ + α(1−ρ)`), then simulate correlated shocks with a Cholesky factor |

**How a stress run works (it's a saga, ARC §7.6):**

1. `POST /v1/risk/stress-runs {portfolio_id, scenario_code, synthetic_market?: {calibration_id}}` → save `stress_run` status `pending`, return 202.
2. Get positions: M5's **local projection** of `portfolio.*` events (so Trading redeploying doesn't break it); fall back to `GET /state?as_of=`.
3. If a synthetic market is requested, M5 asks M2 for a run and waits for `sim.completed`. If it gets `sim.failed`, the **compensation** marks the stress run `failed` with a reason and publishes `stress.failed`.
4. Worker applies the shock and revalues the portfolio step by step → value path.
5. Results:
   - **Max drawdown** = `max(1 − V_t / max_{s≤t} V_s)`
   - **VaR/CVaR** from the simulated loss distribution
   - **Recovery days** = first `t` after the trough where `V_t ≥ V_0` (or "not recovered")
   - **Recovery trajectory** = the whole `V_t` series (FR-RSK-009)
   - **Contribution per instrument** = `qty × (P_after − P_before)` / total loss (FR-RSK-006/007), plus by sector/country (FR-RSK-008)
   - **Concentration (FR-RSK-018):** largest single weight, largest sector weight, **Herfindahl index** `HHI = Σ wᵢ²`, before and under stress
6. Publish `stress.completed`.

#### Part 2: TDA pipeline (FR-RSK-010 to 017)

```
1. correlation matrices   ← ONE batched call to M1 (window, step), fingerprints stored
2. distance matrix        D_ij = sqrt(2 × (1 − ρ_ij))          (valid metric, 0 = identical)
3. Vietoris–Rips complex  ┐
4. persistent homology    ┘ giotto-ph: dims H0 (clusters) and H1 (loops)
5. Betti numbers          β0(ε), β1(ε) = number of bars alive at each threshold ε
6. persistence landscape  persim → λ_k(t) functions for H1
7. topological risk score L1/L2 norm of the landscape, standardized against its own history
Δ  regime transition      distance between consecutive landscapes > rolling mean + 2σ
```

```python
# domain/tda/pipeline.py (sketch)
from gph import ripser_parallel
from persim.landscapes import PersLandscapeApprox
import numpy as np

def analyse_window(corr: np.ndarray, grid=np.linspace(0, 2, 200)):
    dist = np.sqrt(np.clip(2.0 * (1.0 - corr), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    dgms = ripser_parallel(dist, metric="precomputed", maxdim=1, n_threads=-1)["dgms"]
    h1 = dgms[1]
    betti1 = [(np.sum((h1[:, 0] <= e) & (h1[:, 1] > e))) for e in grid]
    land = PersLandscapeApprox(dgms=dgms, hom_deg=1, start=0, stop=2, num_steps=len(grid))
    l1_norm = land.p_norm(p=1)
    return {"diagrams": dgms, "betti1": betti1, "landscape": land.values, "l1": l1_norm}
```

- **Score:** `score_t = 100 × sigmoid((L1_t − mean_{252d}) / std_{252d})`, a 0–100 scale that's comparable across baskets.
- **Transition flag (FR-RSK-016):** `d_t = ‖λ_t − λ_{t−1}‖₂`; flag when `d_t` exceeds its rolling mean + 2 standard deviations → publish `regime.transition`.
- Every stage's output is saved (ARC §8.10): `tda_window`, `distance_matrix`, `persistence_diagram`, `betti_sequence`, `persistence_landscape`, `topological_risk_score`, so the UI can show *why* the score moved.
- **Cost guard:** homology cost grows very fast with the number of assets. The API rejects baskets above the plan's cap (e.g. 250); above ~300 the worker switches to GUDHI's **sparse Rips** (`gudhi.RipsComplex(distance_matrix=..., sparse=0.3)`).
- This follows Gidea & Katz (2018), the key reference in the proposal.

#### Part 3: Composite risk score (proposed new FR-RSK-019)

The Risk Hub page (composite 76/100) needs an owner. M5 already has stress and TDA results and receives ML predictions as events, so it computes:

```
composite = w_stress × stress_score + w_tda × tda_score + w_ml × ml_score   (weights in config, default 0.35/0.40/0.25)
stress_score = 100 × clip(max_drawdown_under_worst_scenario / 0.30, 0, 1)
tda_score    = topological risk score (above)
ml_score     = 100 × drawdown-risk probability (or vol-forecast percentile if that model isn't live)
```

It **only uses lenses that have results** and renormalizes the weights (matching the latest POC commit "derive the composite from whichever lenses ran"). It always stores and returns the **breakdown** next to the number, publishes `risk.composite.updated`, and publishes `risk.threshold.breached` when a level changes.

**Data (`risk_db`):** `stress_scenario`, `stress_run`, `stress_result`, `stress_attribution`, `concentration_snapshot`, `tda_window`, `distance_matrix`, `persistence_diagram`, `betti_sequence`, `persistence_landscape`, `topological_risk_score` (hypertable), `composite_risk_score` (hypertable), `position_snapshot` (projection), `prediction_ref` (projection), `job`.

**Frontend pages:** Risk Analysis, Stress Testing, TDA Analysis (+ pipeline nav), Risk Hub (composite), Attribution.

---

### M6 · Explainability (XAI)

**What it does (simply):** answers "**why?**". Which features pushed a prediction up or down, which holdings caused a loss, and a plain-English paragraph a non-expert can read. If the AI writer is down, it still gives a template-based explanation.

**Libraries**

| Library | Used for |
|---|---|
| `shap` (`TreeExplainer`) | Exact, fast feature attributions for LightGBM/XGBoost models (FR-XAI-001) |
| `shap` (`KernelExplainer` / `DeepExplainer`) | Fallback for non-tree models (slower; use a small background sample) |
| `statsmodels` | Factor risk decomposition by regression on Fama-French factors (FR-XAI-003, Extended) |
| `anthropic` SDK (or any provider SDK behind an interface) | Natural-language narration (FR-XAI-005) |
| `jinja2` | Templated fallback narration |
| `aiobreaker` (from template) | Circuit breaker around the LLM call |

**How it works**

1. **Triggered by events:** consumes `prediction.ready` and `stress.completed` (and composite updates). It saves a small local summary and enqueues an explanation job.
2. **SHAP for a prediction:**
   - Get the explanation bundle from M4's API (the model artifact URI + the **frozen feature vector** used for that prediction).
   - Load the model from R2 (cached on local disk by version hash).
   - `explainer = shap.TreeExplainer(model); values = explainer(feature_vector)`
   - Save the top contributions: `[{feature: "vol_20d", value: 0.034, contribution: +0.25}, …]`
3. **Asset contribution to P&L (FR-XAI-002):** from M3's point-in-time state: contribution_i = `qty_i × ΔP_i`, sorted.
4. **Factor decomposition (FR-XAI-003, Extended):** regress portfolio returns on Fama-French factors (Kenneth French data) + rate changes (FRED): `r_p = α + Σ βₖ fₖ + ε`. Risk share of factor k = `βₖ² var(fₖ) / var(r_p)` (with covariance terms).
5. **Event-to-impact link (FR-XAI-004, Extended):** event study: abnormal return = actual − expected (market model) over [−1, +3] days around a news/8-K event; link only if significant.
6. **Narration (FR-XAI-005):**
   - Build a **strict, factual prompt** from numbers only: the metric, its value, the top 3–5 SHAP drivers with signs, the asset contributions. Tell the model to use only these facts and invent nothing.
   - **Cache key** = hash(template version + input numbers), so the same explanation is never paid for twice.
   - Wrap the call: 8-second timeout, circuit breaker, 1 retry.
   - **If the LLM fails:** fill a Jinja2 template:
     *"{{metric}} is {{level}} at {{value}}. The biggest driver is {{d1.name}} ({{d1.sign}}{{d1.pct}}), followed by {{d2.name}} ({{d2.sign}}{{d2.pct}})."*
   - Save which path produced it (`llm` / `cached` / `template`). Never invent an explanation (ARC §11.1).
7. Publish `explanation.ready`.

**LLM choice:** a small, cheap hosted model is enough for short, factual paragraphs (for example `claude-haiku-4-5`). Check current per-token pricing before finalizing the cost model. Cost stays low because narration is cached per unique input and is only generated for alerts, stress results and predictions a user opens. **Why not a local open model on our server:** on 2 CPU cores a local 7B model takes tens of seconds per paragraph and competes with Monte Carlo for CPU. It stays an option (via **Ollama**) for offline demos.

**Data (`xai_db`):** `shap_attribution`, `contribution_analysis`, `risk_decomposition`, `event_impact_link`, `nl_explanation` (text, source, model, template_version, input_hash), `prediction_ref`, `stress_ref`.

**Frontend pages:** Explainability / Explanations, the "Explain this" button (`ExplainThis.tsx`), narration inside alerts.

**Watch-outs:** only one service holds the LLM API key (M6). Log token usage per request as a metric so cost is visible.

---

### M7 · Dashboard & Alerting

**What it does (simply):** feeds every dashboard widget from **its own copy** of the data (so pages load fast even if another service is slow), holds all live browser connections, and sends alerts **once per problem, not once per event**.

**Libraries**

| Library | Used for |
|---|---|
| `sse-starlette` | Server-Sent Events for alerts/progress |
| FastAPI WebSockets | Replay controls |
| `redis` (async, pub/sub) | Sending a push to whichever API replica holds the user's connection |
| `weasyprint` | PDF report export |
| `resend` | Email alerts |
| `polars` | Building report tables |

**Read models (ARC §5.10, §8.12).** Consumers turn events into query-shaped tables in `dashboard_db`:

| Projection table | Built from | Used by widget |
|---|---|---|
| `rm_portfolio_overview` | `portfolio.*`, `fill.*` | Portfolio overview, KPI cards |
| `rm_drawdown_series` (hypertable) | `portfolio.updated` | Drawdown chart |
| `rm_stress_summary` | `stress.completed` | Stress results |
| `rm_regime_topology` | `regime.transition`, TDA scores | Regime timeline, topological risk |
| `rm_composite_risk` | `risk.composite.updated` | Risk Hub, top bar badge |
| `rm_prediction_latest` | `prediction.ready` | ML panels |
| `rm_explanation` | `explanation.ready` | Narration next to metrics |

- Each widget query reads **one table in one database** (NFR-PERF-001: < 2 s p95), with a Redis cache in front.
- Every response includes `as_of` and `lag_seconds`, and the UI shows a staleness badge (NFR-INT-007).
- A projection can be **rebuilt from scratch** by resetting its consumer group offset to the beginning of the retained topic (NFR-REC-003).
- Continuous aggregates downsample long value series for charts.

**Alert rules (FR-DSH-005 to 007, 009)**

```json
{ "rule_id": "…", "owner": "…", "subject_type": "portfolio", "subject_id": "…",
  "metric": "composite_risk", "operator": ">=", "threshold": 70,
  "clear_threshold": 65, "cooldown_minutes": 240, "channels": ["push", "email"] }
```

`clear_threshold` below `threshold` (hysteresis) stops flapping when a value hovers around the limit.

**The evaluator (a continuous worker):**

```
for each relevant event:
   rules = rules matching (metric, subject)
   for each rule:
      value = event value
      state = alert_rule_state[rule]                 # 'clear' or 'firing', last_notified_at
      if state == clear  and value crosses threshold:   → FIRE
      if state == firing and value below clear_threshold: → RESOLVE
      if state == firing and still bad and now − last_notified ≥ cooldown: → RE-NOTIFY
FIRE:
   INSERT INTO alert_trigger (dedup_key, …) ON CONFLICT (dedup_key) DO NOTHING
     dedup_key = hash(rule_id, subject_id, event_id or window_id)
   if a row was inserted: set state=firing, outbox alert.triggered
notification = side effect of the state change only, never of the event arriving
```

Delivery: an `alert.triggered` consumer publishes to Redis channel `user:{id}` → whichever API replica holds that user's SSE connection sends it. It includes the XAI narration if already available; otherwise the alert goes out immediately and the narration follows (ARC §9.6).

**Acknowledgement (FR-DSH-006):** `POST /v1/dashboard/alerts/{id}/ack` sets `acknowledged_at` and `acknowledged_by`.

**Job progress:** consumes `sim.progress` etc. and pushes to the user who started the job.

**Reports (proposed FR-DSH-010):** a worker renders HTML → PDF with WeasyPrint (or CSV/Parquet with polars), uploads to `r2://quantsim-exports/…` with a 7-day lifecycle rule, and returns a short-lived presigned download link.

**Layouts (FR-DSH-003/004, Extended):** `dashboard_layout(user_id, layout jsonb)`.

**Data (`dashboard_db`):** the `rm_*` projections, `alert_rule`, `alert_rule_state`, `alert_trigger`, `dashboard_layout`, `report_job`.

**Frontend pages:** Dashboard, Alerts, Reports, top bar risk badge, System Activity drawer.

---

### API Gateway

**What it does:** the only public entry point. TLS, route `/v1/<service>/…` to the right service, verify the JWT, rate limit. **It never decides permissions** (AD-18).

**Implementation (Traefik v3):**
- **TLS:** Cloudflare in front (free) + Traefik with Let's Encrypt or a Cloudflare origin certificate.
- **Routing:** Docker labels, e.g. `traefik.http.routers.sim.rule=PathPrefix(`/v1/simulation`)`.
- **JWT check:** a JWT middleware plugin (verifies the EdDSA signature against M0's JWKS), or `forwardAuth` to a tiny internal verifier endpoint. Invalid tokens are rejected at the edge; the verified identity is passed inward in headers **and** every service re-verifies the token (defence in depth).
- **Rate limiting:** Traefik `rateLimit` middleware per IP. Per-user/per-plan limits are enforced in the template with Redis counters, because those need the user identity.
- **Correlation id:** a middleware adds `X-Correlation-Id` if missing; OpenTelemetry starts the trace here.
- **Merged OpenAPI:** CI merges all services' OpenAPI files into `contracts/openapi/gateway.json`, which the frontend generates its client from.

---

## 8. One request end to end

**"A Quant clicks Run on a Monte Carlo simulation"**

| Step | Where | What happens | Tech |
|---|---|---|---|
| 1 | Browser | `POST /v1/simulation/runs` with the access token | TanStack Query mutation, openapi-fetch |
| 2 | Gateway | TLS, JWT signature check, rate limit, route to M2, add correlation id | Traefik |
| 3 | M2 API | Re-verify JWT, check role `quant`, validate body, check plan limits | FastAPI + qs_template |
| 4 | M2 API | One transaction: insert `run` (queued) + `job` + outbox `sim.queued` | SQLAlchemy |
| 5 | M2 API | Enqueue Celery task, return `202 {run_id}` (< 800 ms) | Celery → redis-queue |
| 6 | M2 worker | Claim job (lease), split into shards, generate paths | NumPy/Numba |
| 7 | M2 worker | Every 10%: outbox `sim.progress` | outbox drain → Redpanda |
| 8 | M7 consumer | Receives progress → Redis pub/sub `user:{id}` | confluent-kafka, Redis |
| 9 | M7 API | Pushes the progress event over SSE to the user's browser | sse-starlette |
| 10 | M2 worker | Writes statistics + paths/quantiles (COPY / Parquet → R2), outbox `sim.completed` | asyncpg, pyarrow |
| 11 | M7 / M5 / M3 | M7 updates projections; M5 continues any waiting stress saga | consumers |
| 12 | Browser | SSE event → invalidates the query → fan chart renders | TanStack Query, ECharts |
| – | Everywhere | One trace in Grafana shows all hops, including the async worker (span links) | OpenTelemetry |

---

## 9. Free data APIs we plug in

> ⚠️ **Most free tiers are for personal/non-commercial use.** Fine for the FYP and a free research tier; **budget a paid licence before charging users** (the pricing doc's Databento line). Limits below were checked September 2026 and can change.

| Source | What we get | Free terms (Sept 2026) | Used in | Requirement |
|---|---|---|---|---|
| **Tiingo** | Daily prices (30+ years), split factors, dividends | ~1,000 requests/day, 50/hour, 500 unique symbols/month | M1 primary price adapter | FR-MKT-002, FR-MKT-010 |
| **Massive** (formerly Polygon.io) Basic | Daily bars, 2 years | 5 calls/minute | M1 fallback + cross-check | FR-MKT-011 |
| **Alpha Vantage** | Daily prices, some fundamentals | 25 requests/day | M1 last-resort fallback | – |
| **Binance public data** (`data.binance.vision`) | Real historical crypto **trades and 1-minute bars** as bulk files | Free, no key | M1 replay (real tick data) | FR-MKT-007, FR-TRD-006 |
| **Coinbase Exchange public API** | Live/public crypto trades | Free public endpoints | M1 replay (optional live demo) | FR-MKT-007 |
| **Finnhub** | Company news with tickers | ~60 calls/minute, non-commercial | M1 news adapter | FR-MKT-006 |
| **GDELT DOC 2.0** | Global news search | Free, no key | M1 news adapter (macro news) | FR-MKT-006 |
| **SEC EDGAR** (`submissions`, filings) | SIC sector code, company location, **8-K filings with event item codes** | Free, ≤ 10 requests/second, User-Agent required | M1 reference data, M4 event labels, M6 event impact | FR-RSK-008, FR-ML-007, FR-XAI-004 |
| **OpenFIGI** | Stable instrument identifiers from tickers | Free (higher limits with a free key) | M1 instrument master | FR-MKT-001 |
| **FRED** (St. Louis Fed) | Risk-free rate (3-month T-bill), VIX, interest rates | Free API key | M4 features + Sharpe/alpha, M6 factor decomposition | FR-ML-006, FR-XAI-003 |
| **Kenneth French Data Library** | Fama-French factor returns | Free CSV downloads | M6 factor decomposition, M4 alpha/beta | FR-XAI-003 |
| **Hugging Face Hub** | FinBERT, GLiNER model weights | Free, open weights | M4 | FR-ML-004, FR-ML-007 |
| **Cloudflare Turnstile** | Bot check on signup/login | Free | Frontend + M0 | Pricing doc risk #3 |
| **GitHub OAuth** | Login + account-age check for free tier | Free | M0 | Pricing doc risk #3 |
| **Resend** | Transactional email | 3,000 emails/month | M0, M7 | FR-DSH-007 |

**Libraries that replace paid APIs:** `exchange_calendars` (trading calendars), `spaCy` + `rapidfuzz` (entity linking), FinBERT (sentiment, instead of a paid sentiment API).

**How adapters are built (M1):** each source is one class implementing a small interface, so adding or swapping a vendor never touches the cleaning gate:

```python
class PriceSource(Protocol):
    name: str
    async def fetch_daily(self, symbol: str, start: date, end: date) -> pl.DataFrame: ...

class TiingoSource:       # infrastructure/adapters/tiingo.py
    name = "tiingo"
    async def fetch_daily(self, symbol, start, end):
        r = await self.client.get(f"/tiingo/daily/{symbol}/prices",
                                  params={"startDate": start, "endDate": end})
        return pl.DataFrame(r.json()).select(...)
```

Each adapter has its own Redis token-bucket rate limiter set **below** the vendor's limit, and caches raw responses in `staging_bar` so re-runs don't burn quota.

---

## 10. Repository layout

One monorepo (simpler for 3 people), with **independent images and pipelines per service**.

```
QuantSim/
├─ frontend/                         # current POC moves here
│  ├─ src/
│  │  ├─ components/ pages/ hooks/   # (existing)
│  │  ├─ services/api/               # NEW generated client + TanStack Query hooks
│  │  ├─ services/live/              # NEW SSE / WebSocket hooks
│  │  └─ services/mock/              # kept behind VITE_USE_MOCKS for offline demos
│  └─ package.json
├─ libs/
│  └─ qs_template/                   # shared service template (§6)
├─ services/
│  ├─ platform/                      # M0
│  ├─ market/                        # M1  (+ adapters/, worker/)
│  ├─ simulation/                    # M2  (+ domain/models/, worker/)
│  ├─ trading/                       # M3  (+ engine/)
│  ├─ ml/                            # M4  (+ training/, onnx/, worker/)
│  ├─ risk/                          # M5  (+ domain/stress, domain/tda, domain/composite, worker/)
│  ├─ xai/                           # M6  (+ templates/, worker/)
│  └─ dashboard/                     # M7  (+ projections/, evaluator/, reports/)
├─ contracts/
│  ├─ events/                        # JSON Schema per event type + version
│  └─ openapi/                       # exported specs (generated by CI)
├─ ci/
│  ├─ components.conf                # every deployable component and the paths that define it
│  ├─ scripts/                       # build, promote, deploy, smoke test, rollback, release
│  └─ jenkins/                       # Jenkins image, pinned plugins, configuration as code
├─ deploy/
│  ├─ compose/docker-compose.yml     # one stack for every environment, run per project (qs-dev, qs-test, ...)
│  ├─ env/                           # dev, test, acc, prod settings
│  ├─ compose/postgres-init/         # creates 8 databases + 8 roles
│  ├─ k3s/                           # Kubernetes manifests / Helm chart per service
│  ├─ tofu/                          # OpenTofu: servers, DNS, R2
│  └─ secrets/                       # SOPS-encrypted files
├─ notebooks/                        # research + Kaggle/Colab training notebooks
├─ docs/                             # ARC, REQ, this document
├─ pyproject.toml                    # uv workspace root
├─ Jenkinsfile                       # the single pipeline for every branch
└─ VERSION                           # release version, tagged on main
```

---

## 11. Testing, CI/CD and observability

### 11.1 Testing

| Level | Tool | What it checks |
|---|---|---|
| Domain unit tests | `pytest` | Maths: GBM moments match theory, OU mean reversion, VaR on known distributions, Betti numbers on toy shapes (a circle has β1 = 1) |
| Property tests | `hypothesis` | Invariants: portfolio value = cash + Σ positions; replaying the log equals live state |
| Database tests | `pytest` + `testcontainers` (real Postgres+Timescale) | Constraints: mismatched calibration rejected, inverted replay rejected, append-only tables refuse UPDATE |
| Event tests | `testcontainers` (Redpanda) | Duplicate events cause no double effect; outbox survives a broker outage |
| Contract tests | `schemathesis` on OpenAPI; JSON Schema compatibility check in the schema registry | Breaking API/event changes fail the provider's pipeline (NFR-MNT-005) |
| ML leakage test | `pytest` | Features requested as of `t` never include `knowledge_time > t` |
| Frontend | `vitest`, Testing Library | Components and hooks |
| End to end | `Playwright` | The full demo flow: login → simulate → portfolio → stress/TDA/ML → composite → alert |
| Load | `k6` | Dashboard p95 < 2 s, CRUD p95 < 800 ms |

### 11.2 CI/CD (Jenkins)

CI/CD runs on a self-hosted **Jenkins** controller (`ci/jenkins/`) instead of GitHub Actions, so the team owns the build server, the approval gates and the deploy credentials. Full detail is in `docs/ci-cd.md`.

**Branch flow:** `feature/*` → `develop` (DEV) → `test` (TEST) → `acceptance` (ACC) → `main` (PROD). `develop-poc` keeps the original POC and is never built; `master` stays empty.

**One `Jenkinsfile` for every branch.** It only orchestrates; each step is a script in `ci/scripts/` that also runs on a laptop.

1. **Checks on every branch and pull request:** ShellCheck on the CI scripts; frontend `npm ci` → `oxlint` → `tsc` → `vitest` (with coverage) → `vite build`; for each service in `services/*`: `uv sync` → `ruff` → `mypy` → `pytest`, then `alembic upgrade head` → `downgrade base` → `upgrade head` on an empty PostgreSQL + TimescaleDB (NFR-REC-001).
2. **Build once:** on `develop`, each component image is tagged with a **content hash** of the files that define it and pushed to GitHub Container Registry only if that hash is new.
3. **Promote, never rebuild:** `test`, `acceptance` and `main` re-tag the image `develop` already built and verified, so every environment runs the same bytes.
4. **Deploy and smoke test:** DEV and TEST run on the Jenkins host with Docker Compose behind Traefik; the ACC and PROD frontend is published to Cloudflare Pages. The smoke test checks that the environment serves the exact content hash just deployed. ACC and PROD roll back automatically when it fails.
5. **Gates:** an approver signs off ACC and approves PROD. Jenkins posts `quantsim/dev-verified`, `quantsim/test-verified` and `quantsim/acceptance-signoff` commit statuses, and branch protection requires them on each promotion pull request.
6. **Release:** `main` tags the commit `v<VERSION>` and the images with the same version.

Multi-arch images (`linux/arm64`) are switched on with `PLATFORMS` once an environment runs on the Oracle or Hetzner ARM server; backend services reach ACC and PROD by pointing `COMPOSE_TARGET` at that server over SSH.

**Why Jenkins:** the team chose to self-host CI/CD rather than rely on GitHub Actions. Woodpecker CI was also considered; it is lighter, but it has no approval step inside a running pipeline and no per-environment lock, which the acceptance sign-off and the one-deploy-at-a-time rule depend on.

### 11.3 Observability

- **OpenTelemetry SDK** in the template → an **OpenTelemetry Collector** container → **Grafana Cloud** (free tier covers traces, logs and metrics at our size).
- **Sentry** (free Developer plan) for exceptions in the backend and frontend.
- **Metrics every service emits** (NFR-OBS-002/003): request latency/error rate, per-dependency latency, circuit-breaker state, retry count, Celery queue depth and job duration, **consumer lag per group**, **outbox backlog and oldest unpublished row age**, saga compensations.
- **Dashboards:** one per service + one platform overview. **Alerts** to the team (Grafana → email/Discord): outbox age > 60 s, consumer lag > 5 minutes, queue depth > 100, any service unhealthy.

---

## 12. Cost by phase

Numbers are taken from the pricing document and adjusted for the tool changes in this guide.

| Phase | Users | Runs on | Monthly |
|---|---|---|---|
| **Development** | team | Laptops with Compose profiles | **$0** |
| **Phase 0: demo, defence, early users** | ≤ ~150 | **Oracle Cloud Always Free ARM** (2 OCPU, 12 GB RAM, 200 GB disk) + Cloudflare Pages/R2/DNS + Grafana Cloud free + Sentry free + GitHub | **$0** + LLM usage (cached, small) + domain name |
| Backup plan for Phase 0 | same | One small Hetzner ARM cloud server (~8 vCPU / 16 GB class) | roughly €15–20. **Check current Hetzner prices**: they changed in June 2026 |
| **Phase 1** | ≤ ~1,500 | 1 dedicated batch server + 1 app/database server (pricing doc) + **paid market-data licence** | ~$485 |
| **Phase 2** | ≤ ~15,000 | Multiple batch nodes, Postgres primary + replica, 3-broker Redpanda, k3s, OpenBao | ~$3,800 |

**Why it fits in 12 GB for Phase 0 (estimated memory budget):**

| Component | Estimated RAM |
|---|---|
| 16 Python containers (8 APIs + 7 workers + evaluator), 1 process each | ~3.5 GB |
| PostgreSQL + TimescaleDB (`shared_buffers=1GB`) + PgBouncer | ~2 GB |
| Redpanda (`--memory 1G`, dev mode) | ~1 GB |
| Redis cache + Redis queue | ~0.5 GB |
| Traefik + OpenTelemetry Collector | ~0.2 GB |
| FinBERT via ONNX Runtime (inside the ML worker) | ~0.3 GB |
| **Total** | **~7.5 GB** (with headroom) |

With Apache Kafka + separate schema registry + Vault + MinIO + PyTorch inference, the same setup would need **12 GB+** and wouldn't fit. Those are exactly the swaps this guide makes.

**Where money could leak, and the guard:**
- TDA on huge baskets → asset cap per plan + sparse complexes.
- LLM narration → cache by input hash, only narrate what users open or alerts.
- Free-tier abuse → Turnstile + GitHub account age + per-user rate limits.
- Payments → the pricing doc assumes Stripe fees (2.9% + $0.30). **If the business is registered in Pakistan, Stripe isn't directly available;** a merchant-of-record service (Paddle, Lemon Squeezy) charges more (~5% + $0.50). Confirm before trusting the margin tables.

---

## 13. Changes this proposes to the ARC/REQ documents

These don't change the architecture's style or rules; they settle open questions and fix conflicts.

| ID | Change | Replaces | Reason |
|---|---|---|---|
| **C1** | Event backbone: **Redpanda** (Kafka protocol). Reword AD-15 to "Kafka **protocol** in every environment". | Apache Kafka + separate schema registry | Same semantics, ~⅓ of the memory, built-in registry. |
| **C2** | **Amend FR-SIM-006:** store every path value for runs ≤ 1,000 × 252; for larger runs store seed + config + per-step quantiles and regenerate paths on demand. | "persist every step of every path" (conflicts with the pricing doc) | Keeps exact reproducibility and saves ~60× storage. |
| **C3** | **Add FR-RSK-019: composite risk score** owned by M5, always returned with its breakdown. | (missing) | The Risk Hub page needs an owner. |
| **C4** | **Add FR-DSH-010: report export** (PDF/CSV) owned by M7. | (missing) | The Reports page needs an owner. |
| **C5** | **PostgreSQL 17** in both documents. | PG 16 (ARC) vs 17 (pricing) | One version; current TimescaleDB support. |
| **C6** | Pricing doc §02 data model rewritten to **database per service** (8 databases) with ARC table names. | Single shared schema in the pricing doc | Must match ARC §8.2. |
| **C7** | Job queue: **Celery** (settles "Arq or Celery"). | Arq | Mature retries, priorities, dead-lettering, monitoring. |
| **C8** | Gateway: **Traefik** (settles "Kong/Traefik"). | Kong | Lighter; label-based routing. |
| **C9** | Object storage: **Cloudflare R2** + **SeaweedFS** locally. | MinIO | MinIO community is no longer maintained. |
| **C10** | Secrets: **SOPS + age** now, **OpenBao** later. IaC: **OpenTofu**. | HashiCorp Vault, Terraform | Open-source licences; no secrets server needed early. |
| **C11** | Production orchestration: **k3s**. | Generic Kubernetes (ARC §15 open question) | Real Kubernetes in ~500 MB. |
| **C12** | Contract tests: **Schemathesis** + schema-registry compatibility checks. | Pact / undecided (ARC §15) | No broker service to host. |
| **C13** | Charts: **ECharts + Lightweight Charts + Recharts**. | "ECharts/Plotly" (ARC) vs Recharts (POC) | Each library where it performs best. |
| **C14** | Bulk inter-service transfer: **Arrow IPC over HTTP**. | gRPC for bulk paths | Same speed benefit, no protobuf toolchain. |
| **C15** | Corporate actions: **store both raw and adjusted** series. | Open question (ARC §15) | Tiingo provides both for free; no downstream ambiguity. |
| **C16** | LLM: **hosted model behind an interface, cached, with template fallback**; Ollama only for offline demos. | Open question (ARC §15) | A local model is too slow on 2 CPU cores. |

---

## 14. Build order by iteration

Matches the proposal's four iterations.

| Iteration | Months | Build | Done when |
|---|---|---|---|
| **1: Foundations** | Sep–Oct 2026 | `qs_template` (outbox, consumer, auth, RBAC, OTel, audit trigger) · Compose stack (Postgres+Timescale, Redis ×2, Redpanda, SeaweedFS, Traefik) · **M0** login/users/roles/JWKS · **M1** Tiingo adapter + cleaning gate + returns/vol + correlation API · frontend: API client generation, real login, Market pages on live data · Jenkins pipeline with DEV, TEST, ACC and PROD environments | A bar ingested by M1 appears on the Market Data page through the gateway, with one trace across all hops. |
| **2: Simulate & Trade** | Nov–Dec 2026 | **M2** GBM/OU/jump calibration + Monte Carlo workers + stats · **M3** event log, engine, market/limit orders, cost + slippage, projections, rebuild command · **M1** replay sessions (+ Binance ticks) · **M7** SSE progress + first projections · ECharts fan chart, Lightweight Charts replay | A portfolio runs on a simulated market and on a replay, and rebuilding it from the log gives the identical state. |
| **3: Analytics Core** | Feb–Mar 2027 | **M5** scenario registry, flash crash + vol spike, attribution, concentration; full TDA pipeline + transitions; composite score · **M4** feature store, FinBERT (ONNX), GARCH vol, strategy metrics, MLflow registry | The TDA score and a flagged transition show on the dashboard; the leakage test passes. |
| **4: Explain & Ship** | Apr–May 2027 | **M6** SHAP + narration + template fallback · **M7** alert rules, dedup evaluator, email, reports · regime switching, extra scenarios (Extended, as time allows) · k3s deployment, Grafana dashboards, load tests, Playwright demo flow | The full demo flow runs end to end on the free server; an alert fires exactly once; turning off the LLM still shows explanations. |

---

## 15. Glossary

| Term | Plain meaning |
|---|---|
| **Microservice** | A small, separately deployed program that owns one area (e.g. Simulation) and its own database. |
| **API Gateway** | The single front door every browser request goes through. |
| **JWT** | A signed token that proves who you are; services can check it without calling the login service. |
| **RBAC** | Role-based access control: what Viewer/Analyst/Quant/Admin may do. |
| **Event / event backbone** | A message like "simulation finished" that any service can listen to; Redpanda stores and delivers these. |
| **Outbox** | Saving the event in the same database transaction as the data, so the two can never disagree. |
| **Idempotent** | Doing it twice has the same effect as doing it once. |
| **Saga** | A multi-service workflow where each step can be undone ("compensated") if a later step fails. |
| **Read model / projection** | A service's own copy of another service's data, shaped for its screens and kept updated by events. |
| **Hypertable** | A TimescaleDB table automatically split by time for fast time-series queries. |
| **Event sourcing** | Storing every change as an event forever; current state is calculated from the events. |
| **Monte Carlo** | Simulating thousands of random possible futures to measure risk. |
| **GBM / OU / Jump-diffusion / Regime switching** | Maths models of how prices move: random drift, pull back to an average, sudden jumps, and switching between calm and stressed markets. |
| **VaR / CVaR** | "Loss we won't exceed 95% of the time" / "average loss in the worst 5% of cases". |
| **TDA / Persistent homology** | Measuring the *shape* of data (clusters, loops) and how long those shapes last as you zoom out. |
| **Betti numbers** | Counts of shapes: β0 = number of clusters, β1 = number of loops. |
| **Persistence landscape** | A way to turn those shapes into a function, so different time windows can be compared with a single distance. |
| **Look-ahead bias** | Accidentally training a model with information from the future; our feature store makes it impossible. |
| **SHAP** | A method that tells you how much each input pushed a prediction up or down. |
| **ONNX Runtime** | A fast engine for running trained models on CPU without the full training framework. |
| **Celery worker** | A background process that runs long jobs so the website stays fast. |
| **k3s** | A lightweight version of Kubernetes for running containers in production. |

---

*Sources for vendor limits (checked September 2026): Tiingo ([Find My Moat](https://www.findmymoat.com/tools/tiingo)), Finnhub ([pricing](https://finnhub.io/pricing)), Alpha Vantage ([premium](https://www.alphavantage.co/premium/)), Massive/Polygon ([subscriptions](https://massive.com/knowledge-base/article/what-are-the-different-massive-subscriptions-i-can-use)). Server and storage prices come from `QuantSim-Pricing-and-Unit-Economics.html`. Memory figures are estimates and must be measured on the real stack before the defence.*
