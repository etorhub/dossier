# ARCHITECTURE.md

Technical reference for Dossier. Update this document when architectural decisions change.

---

## System Overview

A Flask web application that fetches news from RSS feeds on a schedule, rewrites clustered stories via the LLM provider abstraction (Ollama locally, Modal vLLM in NAS prod), and presents the daily digest in a clean, accessible reader interface.

The system has no client-side rendering. Flask renders all HTML server-side via Jinja2. HTMX makes targeted requests to Flask routes and swaps HTML fragments into the page. PostgreSQL stores user accounts, fetched articles, stories, rewritten content, and all configuration.

A five-stage pipeline runs on a background schedule (APScheduler): fetch feeds → enrich (extract full text) → embed → cluster → rewrite. When a user opens the app, content is already ready.

### Pipeline Flow Diagram

![Pipeline flow: News Sources → Fetch → Enrich → Embed → Cluster → Rewrite → PostgreSQL](pipeline-flow-diagram.png)

| Stage | Component | What it does |
|-------|-----------|--------------|
| 1. Fetch | `app/feed/` | Fetch RSS feeds, parse XML, classify, deduplicate, insert articles |
| 2. Enrich | `app/extraction/` | Trafilatura extracts full text; re-classifies with full text; updates `articles` |
| 3. Embed | `app/llm/embeddings.py` | `bge-m3` via embedding provider embeds each `news` article; stores vectors |
| 4. Cluster | `app/clustering/` | Cosine similarity + complete-linkage groups related articles into stories |
| 5. Rewrite | `app/services/rewrite_service.py` | Merge sources → single Catalan rewrite (`neutral/ca`); optional proofread pass |

**Content filtering** is applied in stages 1 and 2. The classifier (`app/feed/classifier.py`) uses keyword heuristics to detect non-news content (recipes, horoscopes, classifieds, promotions). Articles classified as `non_news` are stored in the database but excluded from enrichment, embedding, and clustering. Operators can review and override classifications in the ops dashboard.

The worker runs on a schedule (fetch every 60 min; enrich at :05; cluster at :15; rewrite daily at 06:00). When content is ready, any user whose preferred (style, language) matches an existing story rewrite sees it immediately.

---

## Request Lifecycle

### First-time setup

```
User opens app
    → GET /
    → Flask checks: is user logged in?
    → No: redirect to GET /login (or /register for new users)
    → After login, Flask checks: does this user have a profile?
    → No: redirect to GET /setup
    → User fills in: location, language, topics, preferred style (neutral/simple)
    → POST /setup → validate, store in PostgreSQL → redirect to /
```

### Normal open (content already scheduled)

```
User opens app
    → GET /
    → Flask queries PostgreSQL: get stories + cached rewrites for user's (style, language) variant
    → Returns full article list immediately — no LLM calls made
    → User sees today's digest with 3-line summaries
```

### Feed sections (topic filtering)

The main feed shows a section navigation bar built from the user's selected topics (from setup/settings). Each section has a label and icon (configured in `config/app.yaml` under `topics`).

```
User opens app
    → GET /
    → Section nav: "All" | Politics | Society | Culture | … (one per user topic)
    → Clicking a section: GET /?topic=politics
    → Feed filtered to stories matching that topic (article categories or source topics)
    → Category chips on article cards are hidden when viewing a section (redundant)
```

- **All** — shows every story matching the user's sources and topics.
- **Section (e.g. Politics)** — shows only stories where at least one article matches the topic (via RSS categories or the article's source topic list).
- Topic labels and icons are defined in `config/app.yaml` → `topics`. Keys must match topic IDs in `config/sources.yaml`.

### New user before first scheduled rewrite

```
User opens app for the first time after completing setup
    → GET /
    → Flask checks: any cached rewrites for this user's profile?
    → No: return page with message "Your articles are being prepared"
    → APScheduler picks up the new user's profile in the next rewrite cycle
    → On next visit (or via HTMX polling), content is ready
```

### Article expansion

```
User taps "Read more"
    → hx-get="/clusters/<story_id>/expand"
    → Flask queries PostgreSQL: get cached story rewrite for this story + (style, language) variant
    → Returns partials/article_expanded.html with cached content
    → HTMX swaps the partial into #article-{id}
```

---

## Component Map

### `app/feed/`

Responsible for fetching and normalising content from RSS feeds.

For automated source discovery (location-based discovery, feed detection, quality scoring), see `docs/news_source_discovery_agent.md`. The Cursor rule `.cursor/rules/news-source-discovery.mdc` applies when working in this area.

- `fetcher.py` — fetches RSS feeds via HTTP, returns `FetchResult` with content and conditional headers
- `parser.py` — parses feed XML via `feedparser`, returns `RawArticle` objects; extracts best image from `media:content`, enclosures, content HTML, or `media:thumbnail` (in priority order); images from `media:content`/`media:thumbnail` with an explicit width below 300 px are rejected
- `orchestrator.py` — fetches all due feeds, parses, classifies (via `classifier.py`), deduplicates, inserts articles; circuit breaker for failing feeds
- `classifier.py` — heuristic classifier (`classify_article(title, text) → 'news' | 'non_news'`); checks title for strong single-term signals and title+text for multi-signal group patterns (recipes, horoscopes, classifieds, promotions); zero GPU cost
- `availability.py` — `check_all_feeds_availability()`: HTTP HEAD/GET to each active feed; stores results in `source_availability_checks`; scheduled every 10 minutes

A `RawArticle` has: `id`, `title`, `url`, `source`, `published_at`, `raw_text` (RSS description/lede), `full_text` (populated when the source provides full article content), `image_url`, `image_source` (one of `media_content`, `enclosure`, `content_html`, `media_thumbnail`, or `None`).

### `app/llm/`

The LLM abstraction layer. Nothing outside this directory calls Ollama directly.

- `provider.py` — `LLMProvider` abstract base; `OllamaProvider`, `VllmOpenAIProvider`, etc.
- `embeddings.py` — `EmbeddingProvider`; Ollama or vLLM (`bge-m3`)
- `prompts/` — rewrite templates (`rewrite_cluster_neutral.txt`, etc.); simplify/translate prompts exist for multi-language configs

### `app/clustering/`

Article clustering by embedding similarity. Stories are not a fixed partition of all articles — a story is created only when two or more distinct sources cover the same event. Unmatched articles remain unclustered until a second source covers the same story. Uses complete-linkage clustering (every pair in a group must meet the similarity threshold) to avoid chaining unrelated articles.

- `service.py` — embeds articles, clusters by complete-linkage cosine similarity, creates story records for groups with ≥2 distinct sources

### `app/extraction/`

Full-text extraction from article URLs.

- `extractor.py` — batch enrichment for `news` articles with `extraction_status = 'pending'`; after successful Trafilatura extraction, re-runs the classifier with full text and marks any newly-detected non-news articles
- `trafilatura.py` — fetches URL and extracts main body via Trafilatura

### `app/discovery/`

News source discovery: feed detection, validation, quality scoring.

- `feed_detection.py` — validates feed URLs, returns completeness and item count
- `validation.py` — DNS checks, HTTPS validation
- `scoring.py` — quality score from feed completeness, type, frequency, HTTPS

### `app/services/`

Business logic. Routes call services; services do the work.

- `article_service.py` — get today's stories for a user, score and filter by topic, select best image; optional `topic_filter` restricts feed to a single section. Stories are sorted by two-tier key: primary = recency bucket (6-hour windows, most recent first), secondary = `relevance_score` within the same window
- `profile_service.py` — create/update user profile, resolve (style, language) reading variant
- `rewrite_service.py` — cascading rewrite: neutral EN from sources, simplify, translate to all languages; manage cache
- `auth_service.py` — user registration, login, session management

### `app/db/`

All PostgreSQL access. No other module writes to the database directly.

- `articles.py` — read/write for articles (including embeddings, extraction status, `article_type`); all embedding and clustering queries filter `article_type = 'news'`
- `stories.py` — stories, story_articles, story_rewrites
- `sources.py` — news_sources, source_feeds, source_discovery_log
- `rewrite_requests.py` — on-demand rewrite queue infrastructure (table + DB layer exist; not yet wired to routes or scheduler)
- `users.py` — read/write for users and profiles
- `admin.py` — ops dashboard queries (job runs, overview stats, feed health, incidents, stories with rewrite status, user usage)
- `availability.py` — source feed availability check results (insert, history)
- `connection.py` — connection pool management

### `app/routes/`

Flask blueprints. Routes are thin wrappers: parse request, call service, return template.

- `reader.py` — reader interface: guided reading session (`/`), advance a step (`POST /read/advance`), review feed (`/review`, `/feed`), reading stats (`/stats`), story expand/collapse (`/stories/<id>/expand|collapse`), full-page article (`/article/<story_id>`), and legacy `/clusters/<id>/…` redirects
- `auth.py` — login, register, logout
- `setup.py` — initial configuration wizard (`GET /setup`, `POST /setup`)
- `settings.py` — configuration interface; allows editing profile fields after initial setup

### `ops/`

Separate Flask application for operators. Runs on port 5001. Connects to the same PostgreSQL database. No authentication by default.

- `ops/__init__.py` — Flask app factory
- `ops/views/` — dashboard, jobs, sources, articles, stories, users
- `ops/templates/ops/` — Bootstrap 5 + HTMX templates

### `app/templates/` and `ops/templates/`

Jinja2 templates. Main app templates live at project root `templates/`; ops templates live in `ops/templates/ops/`. Pages extend their respective base templates. HTMX responses use partials.

```
templates/                  # Main Dossier reader UI
├── base.html               # Shell: nav (Today/Review/Stats/Settings), font settings; inline <script> for Web Speech API TTS only
├── session.html            # Guided reading session (today's digest, one story at a time) — the `/` view
├── review.html             # Review feed (revisit today's stories, with read markers) — the `/review` view
├── stats.html              # Reading stats: current + longest streak, today's progress — the `/stats` view
├── article.html            # Full-page single article view
├── login.html              # Login page
├── register.html           # Registration page
├── setup.html              # Initial configuration wizard
├── settings.html           # Settings page
└── partials/
    ├── article_card.html         # Summary card (one story in the review list)
    ├── article_expanded.html     # Full simplified article (expanded inline)
    ├── feed_content.html         # Review feed list, loading state, or empty state
    ├── session_step.html         # One story in the guided session (progress bar + article + Next button)
    ├── session_complete.html     # Completion/celebration screen (🎉 + streak)
    └── setup_topics.html         # Topic selection checkboxes (included in setup.html and settings.html)
```

---

## Configuration

All config lives in `config/`. The app reads it at startup. No config is hardcoded.

### `config/app.yaml`

```yaml
llm:
  provider: ollama
  model: qwen2.5:14b # fallback for any task without its own model
  rewrite_model: qwen2.5:14b # merge sources → rewrite in target language
  host: http://ollama:11434
  max_retries: 3

rewriting:
  styles:
    - id: neutral
      label: Neutral
      prompt: rewrite_cluster_neutral
    - id: simple
      label: Simple
      prompt: rewrite_cluster_simple
  languages:
    - id: ca
      label: Catalan
    - id: es
      label: Spanish
    - id: en
      label: English
  default_style: neutral
  default_language: ca

embeddings:
  provider: ollama
  model: bge-m3
  host: http://ollama:11434
  max_retries: 3
  max_input_chars: 8000

schedule:
  fetch_interval_minutes: 60
  enrichment_cron: "5 * * * *"
  cluster_cron: "15 * * * *"
  rewrite_cron: "0 6 * * *"
  availability_check_interval_minutes: 10
  rewrite_batch_size: 0
  rewrite_parallel_workers: 4
  fetcher:
    circuit_breaker_threshold: 5
    request_timeout_seconds: 30
    user_agent: "Dossier/0.1 (+https://github.com/etorhub/dossier)"

extraction:
  enabled: true
  min_content_length: 200
  batch_size: 30
  rate_limit_per_domain: 2.0
  timeout: 30

processing:
  articles_per_day: 0
  summary_sentences: 3
  rewrite_max_tokens: 2000
  cluster_window_hours: 0
  story_similarity_threshold: 0.90
  story_min_sources: 2
  embed_batch_size: 0

relevance:
  weights:
    recency: 0.30      # Freshness from latest article published_at (exponential decay)
    coverage: 0.40     # Distinct outlets in the story (capped at coverage_cap)
    topic_affinity: 0.20  # Share of articles matching user's selected topics
    content_quality: 0.10 # Share of articles with full-text extraction
  recency_half_life_hours: 8
  coverage_cap: 4
  recency_bucket_hours: 6  # Primary sort: most-recent bucket first; relevance_score breaks ties within a bucket
  min_sources: 1

server:
  port: 5000
  debug: false

# Topic labels, icons and emojis. Keys must match topic ids in sources.
topics:
  general: { label: General, icon: newspaper, emoji: "📰" }
  politics: { label: Politics, icon: building, emoji: "🏛️" }
  society: { label: Society, icon: users, emoji: "👥" }
  culture: { label: Culture, icon: palette, emoji: "🎭" }
  international: { label: International, icon: globe, emoji: "🌍" }
  economy: { label: Economy, icon: trending-up, emoji: "📈" }
  science: { label: Science, icon: flask, emoji: "🔬" }
  sports: { label: Sports, icon: trophy, emoji: "⚽" }
```

> **Note:** `SECRET_KEY` is loaded directly from the environment (`.env`) by the Flask app factory — not via `app.yaml`. YAML is for non-secret config only. `rewrite_batch_size` and `embed_batch_size` of `0` remove per-run caps; Ollama uses `llm.max_retries` / `embeddings.max_retries` (default 3) with backoff on transient errors.

**Topics config:** The `topics` block maps topic IDs (from `sources.yaml`) to display labels and icons used in the feed section navigation. Add entries for any topic ID used by sources; `app.config.get_topic_info()` falls back to a generic label/icon for unknown IDs.

### `config/sources.yaml`

Defines the catalog of available sources and their metadata. Each source should include a `topics` list. User selections are stored in PostgreSQL via the setup wizard and settings page.

```yaml
sources:
  - id: "3cat"
    name: "3Cat Notícies"
    domain: "www.3cat.cat"
    homepage_url: "https://www.3cat.cat/"
    country_code: "ES"
    region: "Catalonia"
    languages: ["ca"]
    topics: ["general"]
    full_text: true
    feeds:
      - url: "https://www.3cat.cat/rss/noticia/catala/rss.xml"
        type: rss
        label: main

  - id: "elcritic"
    name: "El Crític"
    domain: "www.elcritic.cat"
    homepage_url: "https://www.elcritic.cat/"
    country_code: "ES"
    region: "Catalonia"
    languages: ["ca"]
    topics: ["politics", "society"]
    full_text: true
    feeds:
      - url: "https://www.elcritic.cat/feed"
        type: rss
        label: main
```

---

## LLM Processing Detail

### Rewrite cascade prompts

The system uses a cascading pipeline for story rewrites. Prompt templates in `app/llm/prompts/`:

- `rewrite_cluster_neutral.txt` — merge sources into neutral English (journalistic, formal).
- `simplify_article.txt` — simplify neutral English to simple English (short sentences, plain vocabulary).
- `translate_article.txt` — translate a finished article to target language, preserving tone.

All prompts produce the same output format (exact headers required by the parser):

```
TITLE:
One headline.

SUMMARY:
{summary_sentences} plain sentences.

FULL:
Full article.
```

### (style, language) variant system

Rewrites are **story-level, not per-user**. The system generates one cached rewrite per `(story_id, style, language)` combination. All users who share the same preferred style and language share the same cached rewrite — the LLM is never called twice for the same combination.

Styles and languages are defined in `config/app.yaml` under `rewriting.styles` and `rewriting.languages`. The two active styles:

| Style ID | Label |
|---|---|
| `neutral` | Neutral |
| `simple` | Simple |

The user's `preferred_style` (set in setup/settings) and `language` together select the correct cached rewrite when they open the feed.

### Rewrite scheduling (cascade)

The daily rewrite job (APScheduler, default 06:00) uses a cascading pipeline:

1. Finds stories missing at least one configured variant (or with `needs_rewrite = true`)
2. For each story: generate neutral English from sources (rewrite prompt)
3. Simplify to simple English (simplify prompt)
4. Translate both to other languages (translate prompt)
5. Stores in `story_rewrites`

Stories that already have all variants are skipped. Per-task models (`rewrite_model`, `simplify_model`, `translate_model`) can be tuned in config for optimal performance.

**Operator backfill:** To re-run the full cascade for stories that already have rewrites (e.g. after changing prompts or models), use the worker CLI command `rewrite-all-stories`. It respects `processing.cluster_window_hours` and `schedule.rewrite_batch_size` and logs job runs as `rewrite_all_stories`. See [docs/TECH_STACK.md](TECH_STACK.md#full-story-rewrite-backfill-rewrite-all-stories).

The `rewrite_requests` table and `app/db/rewrite_requests.py` exist as infrastructure for future on-demand rewrites (triggered when a user saves setup/settings). This is not yet wired to routes or the scheduler; all rewrites are currently driven by the daily batch job.

### Daily digest delivery

The daily digest is an **in-app experience only**. There is no email or push notification. When a user opens the app after the rewrite job has run, their feed shows all stories that have a cached rewrite matching their `(style, language)` variant — no waiting, no loading spinner.

The `user_read_stories` table (defined in migration 010, renamed in 017) tracks which stories each user has read. It is written by `app/db/reading.py` (`mark_story_read`, `get_read_story_ids`) and driven by `app/services/reading_service.py`, which powers the guided reading session's progress and detects when the whole daily digest has been completed (the trigger that advances the reading streak).

### Language and source mismatch

If a user sets `language = "en"` but selects Catalan-language sources, the LLM rewrites the article **in the user's configured language** (English), effectively translating it. The rewrite prompt always specifies the target language. There is no pre-filtering by source language.

Caregivers should be aware of this during setup: the setup wizard should display each source's language so they can make an informed selection. Cross-language selections are allowed; translation is automatic.

---

## Operational Rules

### Ops dashboard

Operators monitor the system via the **ops dashboard** at `http://localhost:5001`. It is a separate Flask service (no auth by default; restrict at network level). The dashboard shows job run history (with trigger: scheduled/manual), feed health, source availability, article pipeline stats, stories with rewrite matrix, user activity, and auto-detected incidents. See [docs/ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md).

### APScheduler and Gunicorn workers

**Hard rule:** APScheduler must only run in the `scheduler` container (entrypoint: `python -m app.scheduler`). It must never be imported or started inside the `web` container.

If APScheduler is started inside a Gunicorn process, every worker spawns its own scheduler, causing every scheduled job to run N times (where N = number of workers). This causes duplicate fetches, duplicate rewrites, and duplicate LLM charges.

- The `web` container runs `gunicorn` only — no scheduler import, no `scheduler.start()` call anywhere in the Flask app factory or any module it imports at startup.
- The `scheduler` container imports and starts APScheduler in `app/scheduler.py` (the `__main__` module), which is a separate process that never handles HTTP requests.
- Do not add `scheduler.start()` to `create_app()` or any Flask init code, even for convenience during development.

---

## What This System Is Not

- Not a scraper. It uses RSS and official APIs.
- Not a republisher. Every article links to and credits the original source.
- Not a single-page application. There is no client-side routing.
- Not cloud-dependent for LLM. It uses Ollama (local) — no API key required; runs fully offline after models are pulled.
