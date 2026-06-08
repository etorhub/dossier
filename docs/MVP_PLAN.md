# MVP Plan — Dossier

Canonical phased plan for the minimum viable product. This document replaces scattered MVP mentions elsewhere.

---

## Vision

> At 07:00 you receive a push: "El teu dossier d'avui és aquí — 10 noves històries."
> You open the app, read 10 well-written stories in Catalan, and you're done for the day.

---

## MVP Scope Summary

| Phase | Deliverable              | Outcome                                                                      |
| ----- | ------------------------ | ---------------------------------------------------------------------------- |
| 0     | Infrastructure & DX      | Docker multi-service, Python tooling, git hooks, conventional commits        |
| 1     | News source catalog      | Populated catalog of validated Catalan/Spanish feeds                         |
| 2     | Fetching pipeline        | Articles stored continuously with full text when available                   |
| 3     | Daily digest engine      | Top-10 stories scored, rewritten in Catalan, push notification sent at 07:00 |
| 4     | Platform                 | Auth, profile config, digest UI                                              |

---

## Phase 0 — Infrastructure & Developer Experience

**Goal:** Establish Docker multi-service setup, Python tooling, Lefthook hooks, and Commitizen before feature development.

### Tasks

1. **Dockerization**
   - `db` — PostgreSQL 18. Persistent volume, health check via `pg_isready`.
   - `web` — Flask app (gunicorn in production, `flask run --debug` in dev).
   - `worker` — APScheduler process. Same image as `web`, different entrypoint.
   - `docker-compose.yml` — Production-like defaults.
   - `docker-compose.nas.yml` — NAS overrides (CPU Ollama, memory limits).
   - `docker-compose.override.yml` — Dev overrides (bind mounts, live reload).
   - `.env.example` — Template for `POSTGRES_PASSWORD`, `SECRET_KEY`, `VAPID_*`.

2. **Python tooling** — Ruff, Mypy, Pytest, Alembic, all via `uv`.

3. **Lefthook** — pre-commit (lint/format), pre-push (test), commit-msg (conventional check).

4. **Commitizen** — Interactive `cz commit` flow, conventional commits enforced.

### Output

`Dockerfile`, `docker-compose.yml`, `docker-compose.nas.yml`, `docker-compose.override.yml`, `.env.example`, `pyproject.toml`, `lefthook.yml`, `alembic/`.

---

## Phase 1 — News Source Catalog

**Goal:** A catalog of validated Catalan and Spanish RSS feeds stored in `sources.yaml`.

**Reference:** `docs/news_source_discovery_agent.md`

### Tasks

1. Seed initial sources manually: 3Cat/CCMA, Vilaweb, El Crític, NacióDigital, RTVE — all open publishers with full-text RSS.
2. For each source: validate DNS, robots.txt, feed availability, full-text vs. description-only.
3. Store in `config/sources.yaml` and sync to `news_sources` / `source_feeds` tables on startup.

### MVP Simplifications

- Single region (Catalonia), single language (Catalan + Spanish sources, output always in Catalan).
- 5–10 sources is enough for MVP.
- Automated discovery (`docs/news_source_discovery_agent.md`) can be added later to expand the catalog.

---

## Phase 2 — Fetching Pipeline

**Goal:** Articles continuously fetched, enriched, clustered, and ready for daily selection.

### Pipeline (continuous)

| Job | Schedule | What |
|-----|----------|------|
| fetch | every 60 min | Fetch all due RSS feeds, store articles |
| enrich | :05 hourly | Extract full text via Trafilatura |
| cluster | :15 hourly | Embed articles (bge-m3) and assign to stories by cosine similarity |
| availability | every 10 min | HTTP HEAD checks on feeds |

### Output

- `articles` table populated with `title`, `url`, `full_text`, `embedding`.
- `stories` table: groups of articles covering the same event.

---

## Phase 3 — Daily Digest Engine

**Goal:** Once a day at 06:00, select the 10 best stories, rewrite them in Catalan, send push notification.

### Tasks

1. **Scoring and selection**
   - `scoring_service.select_top_digest_stories(work, n=10, config)` ranks stories by:
     - Recency (0.30): exponential decay from most recent article
     - Coverage (0.40): number of distinct outlets (capped at 4)
     - Content quality (0.10): share of articles with full text extracted
   - Only stories with `needs_rewrite = True` in the last 48 hours are candidates.

2. **Rewrite**
   - `run_rewrite_batch` filters to top-N before calling the LLM.
   - Single variant: `neutral / ca` (Catalan).
   - No cascading simplify/translate steps.
   - Model: `qwen2.5:3b` on Ollama (CPU, NAS).
   - Output: `TITLE: / SUMMARY: / FULL:` per story, stored in `story_rewrites`.

3. **Push notification**
   - After rewrite completes, `send_digest_ready_notification(n_stories)` fires.
   - Payload: `{ title: "Dossier", body: "El teu dossier d'avui és aquí — 10 noves històries" }`.
   - Uses Web Push + VAPID; reads credentials from `VAPID_PRIVATE_KEY` env var.

### Schedule

```yaml
schedule:
  rewrite_cron: '0 6 * * *'   # 06:00 daily → digest ready at ~07:00

digest:
  top_n: 10
  send_push_notification: true
```

### Output

- `story_rewrites` rows with `style=neutral`, `language=ca` for the top 10 stories.
- Push notification received by all subscribed browsers.

---

## Phase 4 — Platform

**Goal:** Web app: login, setup, digest view.

### Tasks

1. **Auth** — Email + password login; session-based; no OAuth for MVP.

2. **Setup wizard** — Run once after first login: choose topics, rewrite tone.

3. **Digest view** — Main page shows today's 10 stories:
   - Story title + 2-sentence summary
   - Expandable to full rewritten article on tap
   - TTS button (Web Speech API; hidden when not supported)
   - Link to original source

4. **Push subscription** — "Subscribe to notifications" button registers the browser.
   Stored in `push_subscriptions`; used by `send_digest_ready_notification`.

5. **UI requirements**
   - Clean, distraction-free, newspaper-inspired
   - Minimum 48×48px touch targets
   - Base font 22px, line height 1.6
   - No infinite scroll

### Accessibility (non-negotiable)

- Large font, high contrast mode
- Large touch targets throughout
- TTS per story (Web Speech API; hidden when unsupported)
- Configurable detail: headline → summary → full

---

## What the MVP Includes

| Component                                                              | Status |
| ---------------------------------------------------------------------- | ------ |
| Docker multi-service setup (db, web, worker, ollama)                   | ✅     |
| Python tooling (ruff, mypy, pytest)                                    | ✅     |
| Git hooks (Lefthook) and conventional commits (Commitizen)             | ✅     |
| NAS deployment compose file (`docker-compose.nas.yml`)                 | ✅     |
| News source catalog (Catalan/Spanish open publishers)                  | ✅     |
| Continuous fetching and enrichment                                     | ✅     |
| Story clustering (cosine similarity on BGE-M3 embeddings)             | ✅     |
| Daily digest selection (top-10 by recency + coverage)                  | ✅     |
| Rewrite in Catalan only (`qwen2.5:3b`)                                 | ✅     |
| Push notification after daily rewrite                                  | ✅     |
| Auth (email + password)                                                | ✅     |
| Setup wizard (topics, tone)                                            | ✅     |
| Digest view (10 stories, expandable, TTS)                              | ✅     |
| Ops dashboard (port 5001)                                              | ✅     |

---

## What the MVP Excludes (for now)

- Multi-language output (config supports it, not activated)
- Reading streak / gamification — **planned next phase** (see below)
- OAuth or social login
- Paywalled content bypass
- Native mobile app

---

## Future: Reading Streak

Track how many consecutive days the user reads their digest.

**Schema additions needed:**
```sql
ALTER TABLE users ADD COLUMN streak_current INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN streak_best INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN streak_last_read_date DATE;
```

**Logic:** When the user opens the digest and reads at least one story, update `streak_last_read_date = today`. On each page load, compute current streak and display a counter (e.g. "🔥 7 dies seguids").

**Gamification ideas (backlog):**
- Badge milestones (7 days, 30 days, 100 days)
- "You're on a 5-day streak — don't break it!" reminder if no read by 22:00

---

## Success Criteria

- At 07:00 a push notification arrives: "El teu dossier d'avui és aquí"
- Opening the app shows exactly 10 stories in Catalan, clean and readable
- Each story can be expanded to full text; TTS works
- Reading 10 stories takes under 5 minutes
- The pipeline runs unattended; no manual intervention needed
