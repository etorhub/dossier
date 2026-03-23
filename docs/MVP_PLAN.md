# MVP Plan — Dossier

Canonical phased plan for the minimum viable product. This document replaces scattered MVP mentions elsewhere.

---

## MVP Scope Summary

| Phase | Deliverable           | Outcome                                                               |
| ----- | --------------------- | --------------------------------------------------------------------- |
| 0     | Infrastructure & DX   | Docker multi-service, Python tooling, git hooks, conventional commits |
| 1     | News source discovery | Populated catalog of validated feeds                                  |
| 2     | Fetching pipeline     | Articles stored on a schedule with full text when available           |
| 3     | Processing & storage  | LLM rewrites (summary + full rewritten) cached per profile hash       |
| 4     | Platform              | Auth, multi-user profiles, feed UI, daily digest                      |

---

## Phase 0 — Infrastructure & Developer Experience

**Goal:** Establish Docker multi-service setup, Python linting/formatting/type-checking/testing, Lefthook git hooks, and Commitizen conventional commits before feature development.

### Tasks

1. **Dockerization**
   - `db` — PostgreSQL 18 (Alpine). Persistent volume, health check via `pg_isready`.
   - `web` — Flask app serving HTTP only. No background jobs in this process. Runs via `gunicorn` in production, `flask run --debug` in dev.
   - `scheduler` — APScheduler process. Triggers fetch and rewrite jobs on configured intervals. Same Docker image as `web`, different entrypoint (`python -m app.scheduler`).
   - `Dockerfile` — Multi-stage build (builder + runtime). Python 3.12-slim base.
   - `docker-compose.yml` — Production-like defaults (three services: `db`, `web`, `scheduler`).
   - `docker-compose.override.yml` — Dev overrides: bind mounts for live reload, `flask run --debug`, exposed ports.
   - `.env.example` — Template for `POSTGRES_PASSWORD`, `SECRET_KEY` (no LLM API keys; Ollama runs local).

2. **Python tooling (lint, format, type check, test)**
   - Single config: `pyproject.toml`.
   - **Ruff** — Linting (`ruff check`) and formatting (`ruff format`). Rule sets: `E`, `F`, `W`, `I`, `UP`, `B`, `SIM`, `RUF`. Target Python 3.12, line length 88.
   - **Mypy** — Static type checking (`mypy .`). Strict mode, `--ignore-missing-imports` initially.
   - **Pytest** — Testing (`pytest`). Config in `pyproject.toml`, test directory `tests/`.
   - **Alembic** — Database migrations. `alembic init` at project root. `alembic upgrade head` runs on container start. Initial migration creates all tables from scratch. Subsequent schema changes get versioned migration scripts — never modify the initial migration.

3. **Lefthook**
   - Config: `lefthook.yml` at project root.
   - `pre-commit`: `ruff check --fix`, `ruff format --check`, `mypy .`
   - `pre-push`: `pytest`
   - Developer setup: `lefthook install` after cloning.

4. **Commitizen & conventional commits**
   - Config in `pyproject.toml` under `[tool.commitizen]`: `cz_conventional_commits`, `version_provider = "pep621"`, `tag_format = "v$version"`.
   - Interactive flow: `cz commit` (or `cz c`) for conventional commit prompt. Commitizen uses native `git` for the actual commit.
   - Lefthook `commit-msg` hook: `cz check --commit-msg-file $1` to reject non-conforming messages.
   - Bump/changelog (`cz bump`, `cz changelog`) deferred to when releases begin.

### Output

- `Dockerfile`, `docker-compose.yml`, `docker-compose.override.yml`, `.env.example`
- `pyproject.toml` with Ruff, Mypy, Pytest, Commitizen config
- `lefthook.yml` with pre-commit and pre-push hooks
- `alembic/` with initial migration creating all tables

---

## Phase 1 — News Source Discovery

**Goal:** Obtain a catalog of news sources for the target region via automated discovery or manual seeding.

**Reference:** `docs/news_source_discovery_agent.md`

### Tasks

1. **Implement discovery pipeline** (or run as AI-assisted script)
   - Phase 1: Query reference databases (NewsAPI, ABYZ, GDELT, W3Newspapers)
   - Phase 2: Search-based discovery for digital-native outlets
   - Phase 3 (optional for MVP): TLD scan for `full` depth only
   - Phase 4: Validate each candidate (DNS, robots.txt, ToS, feed availability)

2. **Feed detection per source**
   - Try API → RSS/Atom → Google News RSS fallback
   - Store feed URL, type, poll interval in `source_feeds`

3. **Quality scoring**
   - Compute 0–100 score (editorial reputation, frequency, feed completeness, etc.)
   - Use for display ranking and ingestion priority

4. **Output**
   - Populate `news_sources` and `source_feeds` tables (PostgreSQL)
   - For MVP: start with `quick` or `standard` depth for one region (e.g. Catalonia)
   - Initial priority: Open Catalan/Spanish publishers (RTVE, CCMA/3Cat, Vilaweb, El Crític, NacióDigital) — can be seeded manually if discovery is deferred

### MVP Simplifications

- Single region/language for first release (e.g. Catalonia, `ca`/`es`)
- Discovery can run as a one-time or periodic CLI/script; not required to be embedded in the web app
- If discovery is deferred: seed `config/sources.yaml` manually with 5–10 known open publishers

---

## Phase 2 — Fetching Pipeline

**Goal:** Programmatically fetch news from all configured sources on a schedule.

### Tasks

1. **Scheduled fetcher**
   - APScheduler jobs: poll feeds per tiered frequency (high/medium/low based on `avg_articles_per_day`)
   - Respect rate limits, `If-None-Match` / `If-Modified-Since` for conditional GET
   - Parse RSS/Atom via `feedparser`; normalise to `RawArticle` schema

2. **Full-text extraction**
   - Store full content from RSS when available (open publishers with `full_text: true`)
   - Fallback: RSS description/lede only (no paywall bypass)
   - Store both `raw_text` and `full_text` in the `articles` table

3. **Deduplication**
   - Match on `guid` or `(source_id, url)` before insert
   - Update `last_item_guid` / `last_fetched_at` on `source_feeds`

4. **Failure handling**
   - Circuit breaker: after N consecutive failures, mark feed inactive
   - Log to `source_discovery_log` or equivalent for monitoring

### Output

- `articles` table populated with: `id`, `title`, `url`, `source_id`, `published_at`, `raw_text`, `full_text` (when available), `fetched_at`

---

## Phase 3 — Processing & Storage

**Goal:** Rewrite stories via LLM, cache results per (style, language) variant on a schedule. Stories are aggregations of the same news event from different sources — not a fixed partition of all articles. A story is created only when two or more distinct sources cover the same event.

### Tasks

1. **LLM rewriter**
   - For each configured `(style, language)` variant (from `config/app.yaml`), build prompt from `app/llm/prompts/` template
   - Output: headline + N-sentence summary + full rewritten article
   - Store in `story_rewrites` keyed by `(story_id, style, language)`

2. **Scheduled rewriting**
   - APScheduler daily job (configurable time, default 06:00)
   - For each `(style, language)` variant: find stories without a cached rewrite (within the configured cluster window)
   - Two users with the same `preferred_style` and `language` share cached rewrites — the LLM is never called twice for the same combination

3. **Variant system**
   - Styles and languages are defined in `config/app.yaml` under `rewriting.styles` and `rewriting.languages`
   - Active styles: `neutral` (journalistic) and `simple` (plain language)
   - Active languages: `ca` (Catalan), `es` (Spanish), `en` (English)
   - User's `preferred_style` + `language` selects the correct cached rewrite at read time

4. **Daily digest**
   - Select stories for the user filtered by their topic selections
   - Show stories that have a cached rewrite for the user's `(style, language)` variant
   - Fall back to the default variant (`neutral/ca`) if the user's preferred variant is not yet available

### Output

- `story_rewrites` table with `title`, `summary`, `full_text` per `(story_id, style, language)`
- Feed derived from stories + user topic selections + cached rewrites

---

## Phase 4 — Platform

**Goal:** Web app with multi-user accounts, configuration, and accessible feed UI.

End users always access the platform, never the codebase. Flow: **register → configuration page → see content**.

### Tasks

1. **Authentication**
   - User registration (email + password)
   - Multi-user: each account has its own profile, source selections, and topic selections
   - Session-based; no OAuth for MVP
   - Unauthenticated users redirect to login

2. **Profile configuration**
   - Setup wizard (after registration): location, language, topics (all selected by default), preferred reading style (neutral/simple)
   - Settings page: same fields, editable anytime
   - Stored in PostgreSQL: `user_profiles`, `user_topics`

3. **Feed view**
   - Main view: today's articles filtered by user's source/topic selections
   - 3-line summary per article, expandable to full rewritten text on tap
   - One-article-at-a-time mode (no infinite scroll)
   - Large touch targets, high contrast, large font

4. **Daily digest**
   - Top N articles as the default view when opening the app
   - Optional: in-app badge "You have N new articles"

5. **UI requirements**
   - Clean, ad-free
   - Inspiration from a newspaper: courier font, minimalistinc.
   - No clutter; minimal visual noise
   - Link to original source on every article

### Accessibility (non-negotiable)

- Large font, high contrast mode
- Large touch targets throughout
- Text-to-speech per article (browser Web Speech API; hidden when not supported)
- Configurable detail level: headline → summary → full rewritten article

---

## What the MVP Includes

| Component                                                              | Status |
| ---------------------------------------------------------------------- | ------ |
| Docker multi-service setup (db, web, scheduler)                        | ✅     |
| Python tooling (ruff, mypy, pytest)                                    | ✅     |
| Git hooks (Lefthook) and conventional commits (Commitizen)             | ✅     |
| News source discovery (agent or manual seed)                           | ✅     |
| Scheduled fetching from all sources                                    | ✅     |
| Scheduled rewriting (LLM rewrite, cache per story × style × language) | ✅     |
| Multi-user authentication                                              | ✅     |
| Profile configuration (setup wizard + settings)                        | ✅     |
| Feed view (3-line summary, expandable)                                 | ✅     |
| Daily digest (top N articles)                                          | ✅     |
| Clean, ad-free UI                                                      | ✅     |
| Accessibility (large fonts, TTS when supported, one-article-at-a-time) | ✅     |

---

## What the MVP Excludes (for now)

- OAuth or social login
- Paywalled content bypass
- Native mobile app
- Social or sharing features
- Cloud LLM APIs (Anthropic, OpenAI, Gemini) — Ollama is the only supported provider

---

## Suggested Implementation Order

1. **Phase 0** — Docker setup, Python tooling, Lefthook, Commitizen
2. **Phase 4 (auth + setup wizard)** — User registration, login, setup wizard, profile storage
3. **Phase 1** — Discovery or manual seed → `news_sources` + `source_feeds` (or `sources.yaml`)
4. **Phase 2** — Fetcher + scheduler → `articles` populated on schedule
5. **Phase 3** — LLM rewriter + scheduled rewrite pipeline
6. **Phase 4 (complete)** — Feed UI, digest, expandable articles, TTS

Rationale: Phase 0 establishes infrastructure and developer experience before any feature work. Auth and profile storage come next because everything else depends on having users with profiles. The feed UI can be built incrementally as the pipeline behind it comes online.

**Dependency note:** Building the setup wizard (Phase 4a) before the source catalog (Phase 1) means the wizard has no real sources to display. Use a stub: seed 3–5 hardcoded sources in `config/sources.yaml` before Phase 4a so the wizard can render source selection. The stub is replaced by the real catalog when Phase 1 completes. Do not wire up the source catalog to the database until Phase 1 is done.

---

## Database Schema Alignment

The discovery agent doc defines `news_sources`, `source_feeds`, `source_discovery_log`. All use PostgreSQL-native types. The main app schema in `docs/ARCHITECTURE.md` defines `users`, `user_profiles`, `articles`, `stories`, `story_rewrites`, etc.

When discovery is integrated, `articles.source_id` references `news_sources.id`. When using manual `sources.yaml` seeding only, `source_id` is the string ID from the YAML file.

---

## Success Criteria

- A user registers, completes the setup wizard, and sees a feed of rewritten articles on their next visit
- Content is ready when the user opens the app (no loading screens, no waiting for LLM calls)
- End user can read 3-line summaries, expand to full content, use TTS (when browser supports it)
- Multiple users can have independent profiles and see different content based on their selections
- No ads, no clutter, every article links to original source
