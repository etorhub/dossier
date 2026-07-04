# CLAUDE.md — Dossier

Personal daily news digest — curated, rewritten in Catalan, delivered once a day.

---

## Problem Statement

Most news interfaces are built for engagement, not comprehension. They are cluttered, dense, and optimised to keep users scrolling. This project takes a different approach: a curated **daily digest** delivered once a day — the 10 most relevant stories, rewritten in clean Catalan, ready to read in 5 minutes.

The pipeline runs automatically. Once a day at 6:00 the worker scores all clustered stories, picks the top 10 by relevance (recency + multi-source coverage), and rewrites them via LLM. No feed to scroll, no notifications every hour, no noise.

---

## Who We Are Building For

**This is a personal tool, built for personal use.** The content is in Catalan; the digest runs once a day in the morning. The database and auth system support multiple accounts (useful for testing and for family members who might use it), but the design priority is a single user who wants a clean, fast, daily news briefing.

**Neither the end user nor anyone setting up the instance ever needs to touch the codebase.** Access is via the web app only. Creating an account and completing the setup wizard is all that is required.

---

## Deployment Model

The project is open source (AGPL). Two supported targets, one `docker-compose.yml`:

**Local machine (primary — GPU, RTX 4070 or similar):** `docker compose up --build`. Ollama runs with `qwen2.5:14b` (rewrite, ~8.7 GB Q4, fits in 12 GB VRAM) and `bge-m3` (embeddings, 1024-dim, MTEB #1 multilingual). This is the default config in `app.yaml` and the default build — the full pipeline (including all LLM stages) runs here.

**NAS (UGreen DSP 2800, CPU-only) — runs no Ollama.** Same compose file, but Portainer sets `DOSSIER_LLM_JOBS_ENABLED=false` and does **not** enable the `local-llm` profile. The NAS worker runs "light": fetch → enrich → availability only. The GPU-heavy LLM stages (embed + cluster → rewrite → highlight) run **off-host** against the NAS's Postgres — primarily on **Modal (free-tier on-demand GPU)**, or any local/VPS box — over a Cloudflare Tunnel using the scoped `dossier_pipeline` Postgres role. On GPU the off-host runner uses the full `qwen2.5:14b`. See [`docs/DEPLOYMENT_PORTAINER.md`](docs/DEPLOYMENT_PORTAINER.md) (NAS stack), [`docs/REMOTE_REWRITE.md`](docs/REMOTE_REWRITE.md) (off-host setup), and [`deploy/modal/`](deploy/modal/) (Modal runner).

This is a deliberate **light-NAS / full-external split**, driven by the single `DOSSIER_LLM_JOBS_ENABLED` env var (plus `DOSSIER_LLM_MODEL` on the local GPU stack if you want a different model). Keep it that way: don't split the compose file per environment, add GPU device reservations to compose, or invent per-machine overrides beyond these env vars. The off-host runner is the CLI capability `app/worker_cli.py run-llm-stages` (embed+cluster → rewrite → highlight), reached via `scripts/run-remote-pipeline.sh` or the Modal app.

Because the NAS runs no Ollama, it can't produce the digest on its own — the off-host runner is **required daily** for fresh content (the Modal Cron handles this; there is no NAS-side rewrite fallback anymore).

---

## Key Features

### Core: daily digest

Refer to `docs/MVP_PLAN.md` for the phased plan. The core loop is:

1. Pipeline runs continuously: fetch feeds → enrich (full text) → embed → cluster
2. At 06:00, the rewrite job scores all pending stories and selects the top 10 (configurable via `digest.top_n`)
3. Those 10 stories are rewritten in Catalan and cached
4. User opens the app, reads 10 clean stories in ~5 minutes

### Content quality (non-negotiable)

- LLM rewrites produce correct spelling and grammar with no typos
- Output is written exclusively in Catalan — no mixed-language artefacts
- Journalistic tone by default
- Factual accuracy is preserved: the LLM never adds information not present in the source articles

### Accessibility (non-negotiable, not optional)

- Large font, high contrast mode
- Large touch targets throughout — every interactive element must be reachable with imprecise input
- Text-to-speech per article (browser Web Speech API, graceful degradation — if the browser does not support it, the TTS button is hidden rather than broken)
- One-article-at-a-time mode, no infinite scroll
- Configurable detail level: headline → summary → full rewritten article

### User-facing

- Profile configuration (topics, rewrite tone)
- Account management designed to be set up once and left alone
- **Future:** reading streak / gamification (documented in MVP_PLAN.md, not yet implemented)

### Operator-facing

- Ops dashboard at `http://localhost:5001` — separate Flask service for pipeline monitoring, job history, feed health, source availability, articles, stories, user activity, incidents. No auth by default. See `docs/ADMIN_DASHBOARD.md`.

---

## Tech Stack (Summary)

See `docs/TECH_STACK.md` for full details, project structure, dependencies, Docker setup, and key commands.

- **Backend:** Python 3.12+ with Flask
- **Database:** PostgreSQL 18
- **LLM:** Ollama (no API key) via provider interface — `qwen2.5:14b` on GPU (local dev, and the off-host runner for NAS deployments); text generation and embeddings. The NAS runs no Ollama (see Deployment Model).
- **Embeddings:** Ollama (`bge-m3`, 1024-dim) for article clustering — MTEB #1 multilingual, handles Catalan/Spanish cross-lingual pairs accurately
- **Frontend:** Plain HTML + CSS + HTMX
- **Scheduling:** APScheduler runs the pipeline in the worker. On a full (local/GPU) worker: fetch feeds → enrich (extract full text) → embed → cluster → rewrite → highlight. On a light (NAS) worker (`DOSSIER_LLM_JOBS_ENABLED=false`) only the non-LLM stages (fetch → enrich → availability) run; the LLM stages run off-host on a daily schedule (Modal Cron / cron). The rewrite step selects the top 10 stories by relevance score and rewrites them in Catalan only — no cascade, no translation step. Content is ready when the user opens the app.
- **Content filtering:** `app/feed/classifier.py` classifies articles as `news` or `non_news` using keyword heuristics (recipes, horoscopes, classifieds, promotions). Applied at fetch time (title + raw_text) and again at enrich time (full text). Non-news articles are stored with `article_type = 'non_news'` and excluded from enrichment, embedding, and clustering. Operators review and override via the ops dashboard.
- **Packaging:** Docker + docker-compose (db, web, worker, ollama, ops). Web uses slim image; worker uses ollama client; ollama runs models in dedicated container; ops dashboard on port 5001.
- **Dev tooling:** Ruff (lint/format), Mypy (type check), Pytest, Lefthook (git hooks), Commitizen (conventional commits). All tools are managed by **`uv`** — always invoke via `uv run ruff`, `uv run mypy`, `uv run pytest`, etc. Bare tool invocations (e.g. `ruff check`) will use the wrong environment or fail. Lefthook hooks call `uv run` automatically, so `git commit` works without any prefix. `RUFF_CACHE_DIR=/tmp/ruff-cache` is set in `lefthook.yml` to avoid cache permission issues.
- **Branch workflow:** Always `git pull origin master` (or `main`) before creating a new branch to avoid diverged histories.
- **CI/CD pipeline:** GitHub Actions (`.github/workflows/`). `pr-ci.yml` runs CI (lint → type check → test) on pull requests targeting `main` or `master`; both branches are protected and merges require the `ci` check to pass — never bypass branch protection. `publish.yml` builds the `web` and `worker` images on every push to `main` or `master` (and on `vX.Y.Z` tags, plus manual `workflow_dispatch`) and pushes versioned tags to GHCR (`ghcr.io/etorhub/dossier-web`, `ghcr.io/etorhub/dossier-worker`). **The NAS pulls these prebuilt images — it does not build from source.** Compose services reference `image:` (selected by `DOSSIER_TAG`, default `latest`); Portainer redeploys via polling + re-pull (no inbound NAS access needed). Local dev still builds from source — `docker-compose.override.yml` supplies the `build:` directives, so `docker compose up --build` works for contributors. See `docs/DEPLOYMENT_PORTAINER.md`.

---

## Architecture Constraints

These are hard rules, not preferences:

- **Flask routes return HTML only.** Never return JSON to the frontend. Every endpoint renders and returns a Jinja2 template partial. This is HATEOAS — the server owns all state and rendering.
- **HTMX is the only frontend dependency.** No JavaScript frameworks. No build step. No npm. HTMX is loaded via a single CDN script tag. The only permitted JavaScript is a small inline `<script>` block in `base.html` for the Web Speech API (TTS feature detection and playback). No external JS files, no JS libraries beyond HTMX.
- **LLM calls are always abstracted.** Never call Ollama directly from a route. Always go through the provider interface in `app/llm/provider.py`.
- **The pipeline runs on a schedule.** APScheduler in the worker runs: fetch feeds → enrich (Trafilatura extraction) → embed (Ollama) → cluster (cosine similarity) → rewrite (LLM cascade: neutral EN from sources, simplify, translate). When a user opens the app, content is already ready. No on-demand LLM calls during page load. On-demand rewrites (after setup/settings save) are queued in `rewrite_requests` and processed by the worker.
- **Config is never hardcoded.** YAML files define the catalog of available sources/topics and app-level settings. User preferences (location, selected sources, selected topics, filter toggle, rewrite tone, language) live in PostgreSQL, set via the web UI.
- **Multi-user from the start.** The schema, auth, and caching all support multiple independent user accounts.

---

## Coding Rules

- **Internationalization (i18n):** All user-facing strings must be translatable. Use `_()` and `ngettext()` in templates; `gettext()` in Python. Never hardcode UI text. After adding strings, run `pybabel extract`, `pybabel update`, edit `.po` files, then `pybabel compile`. See `docs/I18N.md` and `.cursor/rules/i18n.mdc`.
- Use Python type hints throughout
- Flask routes use blueprints — never register routes directly on the app object
- Template partials (for HTMX responses) live in `templates/partials/` and follow the naming convention `{resource}_{action}.html` (e.g. `article_expanded.html`)
- Never put business logic in routes — routes call services, services do the work
- Database access goes through the db layer (`app/db/`), never raw SQL in routes or services
- Every config value has a documented default in `app.yaml`
- API keys and secrets live in `.env`, never committed to the repo
- All commits follow conventional commit format via Commitizen (`cz commit`); Lefthook enforces this on `commit-msg`

---

## What Claude Gets Wrong on This Stack

- **Hardcoding user-facing strings.** Every UI string must be wrapped in `_()` or `ngettext()` (templates) or `gettext()` (Python). Run the i18n extraction/update/compile workflow after changes.
- **Returning JSON from Flask routes.** Every route must return `render_template(...)` or `render_template_string(...)`. If you find yourself writing `jsonify`, stop.
- **Adding JavaScript frameworks or files.** HTMX attributes on HTML elements handle all interactivity. There is no `static/js/` directory and no external JS libraries. The only permitted JavaScript is a small inline `<script>` in `base.html` for the Web Speech API (TTS). Do not add JS for anything else.
- **Calling Ollama directly.** Always use `from app.llm.provider import get_provider` and call through the interface.
- **Hardcoding source URLs or prompts.** These live in config files.
- **Putting user preferences in YAML files.** User profile settings live in PostgreSQL, set through the setup wizard. Only the source catalog and app-level config belong in YAML.
- **Using SQLite.** This project uses PostgreSQL. Always use `psycopg2` or the db layer, never `sqlite3`.
- **Making LLM calls during request handling.** The web container never imports or runs LLM/ML code. On-demand rewrites (after setup/settings save) are queued in `rewrite_requests` and processed by the worker. Routes serve pre-cached content from the database.
- **Bypassing the content classifier.** All articles inserted via `insert_article()` must have their `article_type` set by `classify_article()` in `orchestrator.py`. Never skip classification or hardcode `article_type = 'news'` unconditionally. The classifier is in `app/feed/classifier.py`.

---

## Token Efficiency

- Before any multi-agent session or worktree feature, invoke the `token-efficiency` skill.
- When dispatching agents (subagent-driven-development or dispatching-parallel-agents): read all files the agent will need upfront and inject them inline. Agents must never read files themselves.
- Branch switches cost a full context reload (~40–70K tokens). Budget: ≤2 per session. Complete all worktree work before switching to main.
- After editing a file, do not re-read it in full. Use grep for targeted verification only.

---

## Content Sourcing

RSS + open publishers are the primary source. Full article text is required for meaningful rewriting — RSS-level text is the fallback for paywalled outlets, not the target. Open Catalan and Spanish publishers (RTVE, CCMA/3Cat, Vilaweb, El Crític, NacióDigital) are the initial priority and provide full content without legal risk.

Full article text is stored in the database when available from open publishers. For paywalled sources, only the RSS description/lede is stored.

No User-Agent spoofing. No paywalled content bypass. Every article links to the original source.

For automated news source discovery (finding feeds by location, validation, quality scoring), see `docs/news_source_discovery_agent.md`.

---

## Legal Considerations

- Self-hosted, private use: minimal legal risk
- Hosted product: always cite and link to the original; transformation must be substantive; never reproduce content that substitutes for the original
- Copyright remains with the publisher — this product is a reading aid, not a republisher

---

## Design Principles

- **Accessibility is a constraint, not a feature.** Good defaults benefit all users: large touch targets, clear typography, and high contrast are the baseline, not a special mode.
- **User setup, user operation.** Every user configures their own feed via the web UI. A family member or caregiver may do this on another person's behalf; the product supports but does not assume that flow.
- **Config-driven throughout.** App config (source catalog, LLM prompts, server settings) lives in YAML. User preferences live in PostgreSQL, set via the setup wizard and settings page.
- **Self-hosted must be genuinely usable.** Whoever deploys (e.g. a family member) should be able to run and maintain it without ongoing help. End users accessing the platform never touch deployment.

---

## Cursor IDE Rules

`.cursor/rules/` contains Cursor IDE rule files that mirror this document. `project-context.mdc` is the full equivalent of CLAUDE.md for Cursor users. Additional rules cover architecture, accessibility, i18n, LLM usage, news source discovery, **database** (`database.mdc`), **testing** (`testing.mdc`), **ops dashboard** (`ops-dashboard.mdc`), and **Docker** (`docker.mdc`). These rules are authoritative for Cursor users and must stay in sync with CLAUDE.md — if one is updated, update the other.

---

## Environment Quirks

- **Alembic**: run via `.venv/bin/python3 -m alembic`, not `.venv/bin/alembic` (shebang points to a stale path).
- **Alembic revision IDs**: use simple numeric strings (`"031"`, `"032"`) matching the existing chain — hex IDs collide and cause `Cycle detected` errors.
- **ruff cache**: if `git commit` fails with "Permission denied" on `.ruff_cache/`, prefix with `RUFF_CACHE_DIR=/tmp/ruff_cache`.
- **Neon migrations**: use the direct endpoint (no `-pooler` suffix) — Alembic needs real Postgres connections, not PgBouncer.
- **Default branch is `main`, not `master`**: the repo's default/active branch is `main` (PRs merge there), even though older docs say `master`. **Any workflow with a branch trigger must list both** (`branches: [main, master]`, mirroring `pr-ci.yml`) and use `{{is_default_branch}}` for the `:latest` tag — never hardcode `github.ref == 'refs/heads/master'`. A `master`-only trigger silently does nothing on a `main` merge (this is exactly how `publish.yml` first shipped broken). When wiring deploys (Portainer ref, etc.), point them at `main`.
- **New GHCR packages are private by default**: the first `publish.yml` run creates `dossier-web`/`dossier-worker` as private. Portainer can't pull them until they're made public (repo → Packages → visibility) or a `read:packages` PAT is added as a Portainer registry. Expect `manifest unknown`/`pull access denied` until both the first publish has run *and* visibility is sorted.
- **Workflow trigger changes take effect from the commit that lands them**: for `push` events GitHub reads the workflow file from the pushed commit, so merging a trigger fix into `main` both fixes future runs and triggers that very run. A `vX.Y.Z` tag push triggers `publish.yml` regardless of branch — handy to seed images before a trigger fix is merged (but the pre-fix version won't push `:latest`).

---

## Out of Scope (for now)

- Multi-language output (currently Catalan only; the config and provider interface support it, but it is not activated)
- Reading streak / gamification (planned feature, not yet implemented — see MVP_PLAN.md)
- Paywalled content bypass
- Training or fine-tuning a custom model
- Native mobile app (web-first, responsive)
- Social or sharing features

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
