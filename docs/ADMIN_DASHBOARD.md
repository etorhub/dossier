# Ops Dashboard

The ops dashboard provides operators with visibility into ingestion pipelines, job history, configured sources, articles, stories, and user activity. It is a **separate service** from the main Dossier web app, intended for the person who deploys and maintains the instance.

---

## Access

- **URL:** `http://localhost:5001` (or your host:5001 when deployed)
- **Authentication:** None by default. The dashboard is intended for private network access. Restrict access at the network/firewall level.

---

## Running the ops dashboard

### Docker

The ops service runs as a separate container:

```bash
docker compose up -d ops
```

Access at `http://localhost:5001`.

### Dev (with override)

```bash
docker compose up ops
```

With the override, the ops service uses Flask debug mode and live reload.

---

## Dashboard sections

### 1. Dashboard (overview)

- **Incidents** — Feed deactivated, extraction backlog, rewrite failures, job errors
- **Overview cards** — Users, articles today, active feeds, last job run
- **Recent jobs** — Last 10 job runs (auto-refresh every 60s)
- **Feed health** — Sources and feeds with availability status
- **Article pipeline** — Extraction status breakdown, 7-day ingestion
- **Stories & rewrites** — Clustering stats, rewrite coverage, recent failures

### 2. Jobs

Paginated table of all pipeline job runs:

- Job name, started, finished, duration, **trigger** (scheduled/manual)
- Status (success, error, running)
- Result (expandable JSON)
- Error message

Filters: job name, status. Auto-refresh every 30s.

### 3. Sources

Table of sources and feeds:

- Source name, domain, country, feed URL
- Poll interval, active, **availability status**
- Consecutive failures, last fetched, last availability check
- **History** button — expandable availability check history

### 4. Articles

Paginated table of fetched articles with full metadata:

- ID, title, source, published, fetched
- Extraction status, method, extracted_at
- Has embedding, story assignment
- Filters: extraction status, source, date range, has-embedding, in-story

### 5. Stories

Paginated table of story clusters:

- Story ID, created, article count, sample titles
- **Rewrite matrix** — per (style × language): done / failed / missing
- **Detail** button — expandable article list
- **Not in story** — per article in the detail row; removes the article from the cluster, records it in `clustering_feedback` for review, and sets **`needs_rewrite`** on that story so the next rewrite job runs the **full cascade** (neutral → simple → translations) from the remaining sources. Flagged stories are included in the rewrite batch even when all member articles are older than `processing.cluster_window_hours`.
- **Clustering feedback** (sidebar) — table of flagged rows, similarity-at-flag, status (`pending` → agent queue, `failed` → retryable error, `reviewed` → done). Agent analysis after review.

Run the feedback agent on **pending** and **failed** rows (worker container, requires LLM/Ollama as for rewrites):

```bash
docker compose exec worker python -m app.worker_cli review-clustering
```

The agent writes `agent_analysis` / `agent_recommendation`, sets **`failed`** (retryable) on LLM/parse/validation/internal errors, **`reviewed`** on success, and may insert rows into `clustering_exclusion_rules`. After each run it **re-applies** active `article_pair` rules to existing memberships (detaches co-located pairs). Re-run only that step:

```bash
docker compose exec worker python -m app.worker_cli apply-clustering-exclusion-rules
```

The hourly cluster job loads active rules and applies them when merging new articles. Migration `022` backfills older error rows from `reviewed` → `failed` where the analysis text matches known failure patterns.

### 6. Users

Table of platform users with usage:

- Email, joined, last login, active
- Language, preferred style, location
- Read stories count, enabled topics

---

## Source availability checks

A scheduled job runs every 10 minutes to check feed reachability (HTTP HEAD/GET). Results are stored in `source_availability_checks` and reflected in the Sources page.

Config: `config/app.yaml` → `schedule.availability_check_interval_minutes` (default 10).

---

## Job run persistence

The scheduler records each job execution in the `job_runs` table:

1. Before running: insert a row with `status = 'running'`, `trigger` (scheduled/manual)
2. On success: update with `status = 'success'`, `result` (JSONB of the report)
3. On exception: update with `status = 'error'`, `error_message`

CLI commands (`fetch-feeds`, `enrich-articles`, etc.) also record runs with `trigger = 'manual'`.

---

## Database tables

### `job_runs`

| Column | Type | Description |
|--------|------|-------------|
| `trigger` | TEXT | `scheduled` or `manual` |
| (others) | | See migration 006 |

### `source_availability_checks`

| Column | Type | Description |
|--------|------|-------------|
| `feed_id` | INTEGER | FK to source_feeds |
| `checked_at` | TIMESTAMPTZ | When checked |
| `is_available` | BOOLEAN | Reachable |
| `http_status` | INTEGER | HTTP status code |
| `response_time_ms` | INTEGER | Response time |
| `error_message` | TEXT | Error if unavailable |

### `source_feeds` (new columns)

| Column | Type | Description |
|--------|------|-------------|
| `is_available` | BOOLEAN | Last check result |
| `last_availability_check_at` | TIMESTAMPTZ | When last checked |

---

## Implementation

- **App:** `ops/` package — separate Flask app
- **DB layer:** `app/db/admin.py`, `app/db/availability.py` — shared with scheduler
- **Templates:** `ops/templates/ops/` — Bootstrap 5 + HTMX
- **Docker:** `ops` service, port 5001, uses web build target
