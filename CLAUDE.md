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

The project is open source (AGPL). The **only** deployment target for the app stack (database, web, worker, ops) is a self-hosted **NAS UGreen DSP 2800** running Docker via `docker-compose.yml`. LLM inference is offloaded to **Modal** GPU functions reached over HTTPS via the provider abstraction — the NAS itself has no GPU and no Docker GPU device reservations. See [`docs/DEPLOYMENT_PORTAINER.md`](docs/DEPLOYMENT_PORTAINER.md) for the Portainer setup guide and [`docs/MODAL_GPU_BACKEND.md`](docs/MODAL_GPU_BACKEND.md) for the Modal deployment.

There is no Raspberry Pi, Oracle Cloud, VPS, or second-machine app deployment path — keep the app stack scoped to the single NAS target. Don't reintroduce split-scheduler modes, GPU device reservations in compose, or multi-machine app compose overrides. The Modal inference dependency is the deliberate exception: it is a managed remote API, not a second app host.

For local development and tests, `COMPOSE_PROFILES=local-llm` starts an Ollama container with lightweight models — no Modal account needed. Provider switching is driven entirely by environment variables (`LLM_PROVIDER`, `EMBED_PROVIDER`).

The NAS's internal 06:00 rewrite schedule is a fallback, not the only way to run that job — it can also be run on demand from a local machine or an ad-hoc/VPS box, against the NAS's production database, over a Cloudflare Tunnel using a scoped `dossier_pipeline` Postgres role. This is an ops/CLI capability (`app/worker_cli.py rewrite-articles`, already existing), not a new scheduler mode. See [`docs/REMOTE_REWRITE.md`](docs/REMOTE_REWRITE.md).

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
- **Daily reading session (gamified):** the home page (`/`) guides the user through today's digest one article at a time; finishing the last one shows a completion/celebration screen. The reading streak (🔥) advances when the **whole digest is completed** (not per-article). A **Review** view (`/review`) revisits stories (with read markers) and a **Stats** view (`/stats`) shows current + longest streak. Backed by the `user_read_stories` table via `app/db/reading.py` and `app/services/reading_service.py`. Remaining backlog (badge milestones, per-user timezone) is tracked in MVP_PLAN.md / TODOS.md.

### Operator-facing

- Ops dashboard at `http://localhost:5001` — separate Flask service for pipeline monitoring, job history, feed health, source availability, articles, stories, user activity, incidents. No auth by default. See `docs/ADMIN_DASHBOARD.md`.

---

## Tech Stack (Summary)

See `docs/TECH_STACK.md` for full details, project structure, dependencies, Docker setup, and key commands.

- **Backend:** Python 3.12+ with Flask
- **Database:** PostgreSQL 18
- **LLM:** Provider abstraction (`app/llm/provider.py`) — **prod (NAS):** `Qwen/Qwen2.5-32B-Instruct-AWQ` served via vLLM on Modal (L40S GPU), reached over HTTPS with bearer auth; **local dev:** Ollama with a small model for fast tests. Switched via `LLM_PROVIDER` env var (`vllm` / `ollama`).
- **Embeddings:** Provider abstraction (`app/llm/embeddings.py`) — **prod (NAS):** `BAAI/bge-m3` served via vLLM on Modal (L4 GPU); **local dev:** Ollama `paraphrase-multilingual`. Switched via `EMBED_PROVIDER` env var.
- **Frontend:** Plain HTML + CSS + HTMX
- **Scheduling:** APScheduler runs the pipeline in the worker: fetch feeds → enrich (extract full text) → embed → cluster → rewrite. The daily rewrite (06:00) selects the top 10 stories by relevance score and rewrites them in Catalan only — no cascade, no translation step. Content is ready when the user opens the app.
- **Content filtering:** `app/feed/classifier.py` classifies articles as `news` or `non_news` using keyword heuristics (recipes, horoscopes, classifieds, promotions). Applied at fetch time (title + raw_text) and again at enrich time (full text). Non-news articles are stored with `article_type = 'non_news'` and excluded from enrichment, embedding, and clustering. Operators review and override via the ops dashboard.
- **Packaging:** Docker + docker-compose (db, web, worker, ops). Web uses slim image; worker calls Modal inference endpoints over HTTPS. `COMPOSE_PROFILES=local-llm` adds Ollama for local dev only — not used in the NAS prod stack. Ops dashboard on port 5001. Modal apps are deployed separately via `modal deploy` (see `modal/`).
- **Dev tooling:** Ruff (lint/format), Mypy (type check), Pytest, Lefthook (git hooks), Commitizen (conventional commits). All tools are managed by **`uv`** — always invoke via `uv run ruff`, `uv run mypy`, `uv run pytest`, etc. Bare tool invocations (e.g. `ruff check`) will use the wrong environment or fail. Lefthook hooks call `uv run` automatically, so `git commit` works without any prefix. `RUFF_CACHE_DIR=/tmp/ruff-cache` is set in `lefthook.yml` to avoid cache permission issues.
- **Branch workflow:** Always `git pull origin master` (or `main`) before creating a new branch to avoid diverged histories.
- **CI/CD pipeline:** GitHub Actions (`.github/workflows/`). `pr-ci.yml` runs CI (lint → type check → test) on pull requests targeting `main` or `master`; both branches are protected and merges require the `ci` check to pass — never bypass branch protection. `publish.yml` builds the `web` and `worker` images on every push to `main` or `master` (and on `vX.Y.Z` tags, plus manual `workflow_dispatch`) and pushes versioned tags to GHCR (`ghcr.io/etorhub/dossier-web`, `ghcr.io/etorhub/dossier-worker`). **The NAS pulls these prebuilt images — it does not build from source.** Compose services reference `image:` (selected by `DOSSIER_TAG`, default `latest`); Portainer redeploys via polling + re-pull (no inbound NAS access needed). Local dev still builds from source — `docker-compose.override.yml` supplies the `build:` directives, so `docker compose up --build` works for contributors. See `docs/DEPLOYMENT_PORTAINER.md`.

---

## Architecture Constraints

These are hard rules, not preferences:

- **Flask routes return HTML only.** Never return JSON to the frontend. Every endpoint renders and returns a Jinja2 template partial. This is HATEOAS — the server owns all state and rendering.
- **HTMX is the only frontend dependency.** No JavaScript frameworks. No build step. No npm. HTMX is loaded via a single CDN script tag. The only permitted JavaScript is a small inline `<script>` block in `base.html` for the Web Speech API (TTS feature detection and playback). No external JS files, no JS libraries beyond HTMX.
- **LLM calls are always abstracted.** Never call Ollama directly from a route. Always go through the provider interface in `app/llm/provider.py`.
- **The pipeline runs on a schedule.** APScheduler in the worker runs: fetch feeds → enrich (Trafilatura extraction) → embed (embedding provider) → cluster (cosine similarity) → rewrite (LLM provider). When a user opens the app, content is already ready. No on-demand LLM calls during page load. On-demand rewrites (after setup/settings save) are queued in `rewrite_requests` and processed by the worker.
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
- **Calling any LLM SDK directly.** Always use `from app.llm.provider import get_provider` and call through the interface. The concrete backend (Ollama locally, vLLM on Modal in prod) is wired by config — routes and services never know which is active.
- **Hardcoding source URLs or prompts.** These live in config files.
- **Putting user preferences in YAML files.** User profile settings live in PostgreSQL, set through the setup wizard. Only the source catalog and app-level config belong in YAML.
- **Using SQLite.** This project uses PostgreSQL. Always use `psycopg2` or the db layer, never `sqlite3`.
- **Making LLM calls during request handling.** The web container never imports or runs LLM/ML code. On-demand rewrites (after setup/settings save) are queued in `rewrite_requests` and processed by the worker. Routes serve pre-cached content from the database.
- **Bypassing the content classifier.** All articles inserted via `insert_article()` must have their `article_type` set by `classify_article()` in `orchestrator.py`. Never skip classification or hardcode `article_type = 'news'` unconditionally. The classifier is in `app/feed/classifier.py`.
- **Widening Postgres's port exposure or reusing the `dossier` role for remote access.** `db` publishes on `127.0.0.1:5432` deliberately loopback-only; external reachability goes only through the Cloudflare Tunnel + Access-gated `dossier_pipeline` role (migration `037`), never the app's main `dossier` role. Don't bind the port to `0.0.0.0`, and don't put the pipeline role's password in a migration or commit — see `docs/REMOTE_REWRITE.md`.

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

- **Modal GPU inference (prod):** LLM and embedding providers switch between Ollama (local dev) and Modal-hosted vLLM (NAS prod) via env vars — `LLM_PROVIDER=vllm`, `LLM_API_BASE=https://<rewrite-app>.modal.run/v1`, `OPENAI_API_KEY=<modal-rewrite-token>`, `EMBED_PROVIDER=vllm`, `EMBED_API_BASE=https://<embed-app>.modal.run/v1`, `EMBED_API_KEY=<modal-embed-token>`. When these vars are unset, the provider falls back to Ollama. See `docs/MODAL_GPU_BACKEND.md`.
- **Alembic**: run via `.venv/bin/python3 -m alembic`, not `.venv/bin/alembic` (shebang points to a stale path).
- **Alembic revision IDs**: use simple numeric strings (`"031"`, `"032"`) matching the existing chain — hex IDs collide and cause `Cycle detected` errors.
- **ruff cache**: if `git commit` fails with "Permission denied" on `.ruff_cache/`, prefix with `RUFF_CACHE_DIR=/tmp/ruff_cache`.
- **Neon migrations**: use the direct endpoint (no `-pooler` suffix) — Alembic needs real Postgres connections, not PgBouncer.
- **Default branch is `main`, not `master`**: the repo's default/active branch is `main` (PRs merge there), even though older docs say `master`. **Any workflow with a branch trigger must list both** (`branches: [main, master]`, mirroring `pr-ci.yml`) and use `{{is_default_branch}}` for the `:latest` tag — never hardcode `github.ref == 'refs/heads/master'`. A `master`-only trigger silently does nothing on a `main` merge (this is exactly how `publish.yml` first shipped broken). When wiring deploys (Portainer ref, etc.), point them at `main`.
- **New GHCR packages are private by default**: the first `publish.yml` run creates `dossier-web`/`dossier-worker` as private. Portainer can't pull them until they're made public (repo → Packages → visibility) or a `read:packages` PAT is added as a Portainer registry. Expect `manifest unknown`/`pull access denied` until both the first publish has run *and* visibility is sorted.
- **Workflow trigger changes take effect from the commit that lands them**: for `push` events GitHub reads the workflow file from the pushed commit, so merging a trigger fix into `main` both fixes future runs and triggers that very run. A `vX.Y.Z` tag push triggers `publish.yml` regardless of branch — handy to seed images before a trigger fix is merged (but the pre-fix version won't push `:latest`).
- **`dossier_pipeline` role starts with no password**: migration `037` creates the role deliberately without one (so no secret lands in git). It must be set once via `ALTER ROLE dossier_pipeline WITH PASSWORD '...'` run manually against the NAS after deploying, or the remote-rewrite path (`docs/REMOTE_REWRITE.md`) stays unusable. Relatedly, `db` now publishes on `127.0.0.1:5432` — loopback-only, reachable only via a process on the NAS host itself (`cloudflared`) — don't widen that binding.

---

## Out of Scope (for now)

- Multi-language output (currently Catalan only; the config and provider interface support it, but it is not activated)
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
