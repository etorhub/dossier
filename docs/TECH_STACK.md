# Tech Stack

Technology choices for Dossier, with rationale.

---

## Documentation map

| Topic | Canonical doc |
| --- | --- |
| NAS deploy + GHCR images | [`DEPLOYMENT_PORTAINER.md`](DEPLOYMENT_PORTAINER.md) |
| Modal GPU inference | [`MODAL_GPU_BACKEND.md`](MODAL_GPU_BACKEND.md) |
| Remote rewrite ops | [`REMOTE_REWRITE.md`](REMOTE_REWRITE.md) |
| Pipeline schedules + stages | [`PIPELINE.md`](PIPELINE.md) |
| Architecture decisions | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| MVP phase history | [`MVP_PLAN.md`](MVP_PLAN.md) |

---

## Core Stack

| Layer | Technology | Why |
| --- | --- | --- |
| Backend | Python 3.12+ with Flask | Lightweight, well-understood, Jinja2 built-in |
| Database | PostgreSQL 18 | Robust, multi-user, JSONB support, wide hosting availability |
| LLM | Provider abstraction (`app/llm/`) | **Local dev:** Ollama (`qwen2.5:14b`, `bge-m3`). **NAS prod:** Modal vLLM (`Qwen2.5-32B-AWQ` rewrite, `BGE-M3` embed) via `LLM_PROVIDER` / `EMBED_PROVIDER` env vars. |
| Frontend | Plain HTML + CSS + HTMX | No build step, no JS framework, server-rendered throughout. See [`docs/DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md). |
| Templating | Jinja2 (Flask built-in) | Tight Flask integration, partial rendering for HTMX |
| Scheduling | APScheduler in dedicated worker container | Web and worker run as separate containers; web has zero ML/LLM deps |
| Packaging | Docker + docker-compose | Single `docker-compose up` runs everything |

---

## Python Dependencies

| Package | Purpose |
| --- | --- |
| Flask | Web framework |
| psycopg2-binary | PostgreSQL driver |
| APScheduler | Background job scheduling (fetch, enrich, cluster, rewrite) |
| feedparser | RSS/Atom feed parsing |
| httpx | HTTP client for feed fetching |
| ollama | Ollama Python client (LLM chat + embeddings) |
| trafilatura | Full-text extraction from article URLs |
| python-dotenv | Load `.env` for secrets |
| bcrypt | Password hashing |
| alembic | Database migrations |
| sqlalchemy | ORM (used by Alembic) |
| gunicorn | WSGI server for production |
| PyYAML | Config file loading |
| humanize | Relative time formatting (e.g. "5 minutes ago") |
| Flask-Babel | Internationalization (gettext, locale selection) |
| ruff | Linting and formatting |
| mypy | Static type checking |
| pytest | Testing |
| commitizen | Conventional commits and version bumping |

---

## Project Structure

```
/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Loads config/*.yaml
│   ├── cli.py               # Flask CLI commands (seed-sources, make-admin, show-rewrite-failures)
│   ├── scheduler.py         # APScheduler entry point (worker container only)
│   ├── worker_cli.py        # Pipeline CLI (fetch-feeds, enrich-articles, cluster-articles, etc.)
│   ├── routes/              # Flask blueprints — reader, auth, setup, settings
│   ├── services/            # Business logic — routes call services
│   ├── llm/
│   │   ├── provider.py      # Abstract LLM interface + Ollama, Gemini, Anthropic, vLLM-compatible
│   │   ├── embeddings.py    # Embedding provider (Ollama bge-m3 / Modal vLLM)
│   │   └── prompts/        # rewrite_cluster_neutral, simplify_article, translate_article
│   ├── feed/                # RSS fetching (fetcher, parser, orchestrator, availability)
│   ├── extraction/          # Full-text extraction (extractor, trafilatura)
│   ├── clustering/          # Article clustering by embedding similarity
│   ├── discovery/           # Feed detection, validation, quality scoring
│   └── db/                  # PostgreSQL access layer (includes admin/ops queries)
├── ops/                     # Ops dashboard — separate Flask app (port 5001)
│   ├── __init__.py          # Ops app factory
│   ├── views/               # Dashboard, jobs, sources, articles, stories, users
│   └── templates/ops/      # Bootstrap 5 + HTMX templates
├── templates/               # Jinja2 templates for main app (at project root)
│   └── partials/            # HTMX fragment templates
├── alembic/                 # Database migration scripts (Alembic)
│   ├── env.py
│   └── versions/            # Versioned migration files
├── config/
│   ├── sources.yaml         # Catalog of available RSS feeds and API sources
│   └── app.yaml             # App-level config (LLM provider, schedule, etc.)
├── translations/            # i18n catalogs (ca, es, en) — see docs/I18N.md
│   ├── ca/LC_MESSAGES/      # Catalan .po and .mo
│   ├── es/LC_MESSAGES/      # Spanish .po and .mo
│   └── en/LC_MESSAGES/      # English .po and .mo
├── scripts/                 # Dev helpers — seed_docker_db.sh, seed_dev_data.py
├── tests/                   # pytest test suite
├── docs/                    # Project documentation
├── .cursor/rules/           # Cursor IDE rules (project-context.mdc = full CLAUDE.md equivalent)
├── CLAUDE.md                # AI assistant context (Claude Code)
├── README.md
├── pyproject.toml           # Ruff, Mypy, Pytest, Commitizen config
├── lefthook.yml             # Git hooks (pre-commit, pre-push, commit-msg)
├── docker-compose.yml
├── docker-compose.override.yml  # Dev overrides (bind mounts, flask run --debug)
├── Dockerfile                   # Multi-target: web (slim), worker (full)
├── requirements.txt            # Worker: feedparser, trafilatura, ollama, etc.
├── requirements-web.txt       # Web: slim deps only (no ollama, no feed processing)
└── .env.example                # Template for secrets (no LLM API keys needed)
```

---

## Key Commands

```bash
# Run the app locally (no Docker)
flask run

# Run with Docker (recommended)
docker-compose up

# Grant admin privileges (for future use; ops dashboard has no auth)
flask make-admin user@example.com

# Pipeline commands (run in worker container)
docker compose exec worker python -m app.worker_cli fetch-feeds
docker compose exec worker python -m app.worker_cli run-pipeline

# Install git hooks (run after cloning)
lefthook install

# Conventional commit (interactive)
cz commit
# or: cz c

# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .

# Update i18n translations (after adding/changing translatable strings)
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
# Edit translations/*/LC_MESSAGES/messages.po, then:
pybabel compile -d translations

# Type check
mypy .
```

### Ops dashboard

Operators can access the **ops dashboard** at `http://localhost:5001` to monitor ingestion pipelines, job history, feed health, source availability, articles, stories, and user activity. It is a separate Flask service with no authentication (intended for private network access). See [docs/ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) for details.

```bash
docker compose up -d ops
```

---

## Docker Composition

See [`docker-compose.yml`](../docker-compose.yml) for the authoritative service definitions. Summary:

| Service | Image / role | Notes |
| --- | --- | --- |
| `db` | `pgvector/pgvector:pg18` | Loopback-only port `127.0.0.1:5432` |
| `db-init` | `ghcr.io/etorhub/dossier-web` | One-shot `alembic upgrade head` |
| `web` | `ghcr.io/etorhub/dossier-web` | Reader app, port **5000** |
| `worker` | `ghcr.io/etorhub/dossier-worker` | APScheduler pipeline |
| `ops` | `ghcr.io/etorhub/dossier-web` | Ops dashboard, port **5001** |
| `ollama` + `ollama-init` | `ollama/ollama` | Profile `local-llm` only (local dev) |

**NAS production** pulls prebuilt GHCR images (`DOSSIER_TAG`); no `build:` in base compose. Inference uses Modal — see [`DEPLOYMENT_PORTAINER.md`](DEPLOYMENT_PORTAINER.md).

**Local dev** auto-merges [`docker-compose.override.yml`](../docker-compose.override.yml): bind mounts, `build:` targets, `flask run --debug`, Postgres on `localhost:5432`.


### PostgreSQL major upgrades (Docker)

The compose file pins a **PostgreSQL major** (see `db.image`). PostgreSQL does not support in-place upgrades by swapping the image tag on an existing data directory. After bumping the major version, **recreate the database volume** (only when you can discard or have dumped the old data):

```bash
docker compose down
docker volume rm "$(basename "$(pwd)")_pgdata"   # or: docker volume ls, then rm the …_pgdata volume
docker compose up -d
```

The `web` service runs `alembic upgrade head` on startup and will apply migrations to the new cluster.

### Optional PostgreSQL 18 tuning

Planner and executor improvements in newer releases apply without app changes. For very large databases or heavy sequential I/O, PostgreSQL 18’s asynchronous I/O may help on Linux hosts that support io_uring; operators can adjust `io_method` and related settings in `postgresql.conf` if benchmarks justify it. Defaults are fine for typical Dossier deployments. See the [PostgreSQL 18 release notes](https://www.postgresql.org/docs/release/18/).

### Local feed without the pipeline

The reader UI needs Flask (HTMX); you can skip **worker** and **Ollama** and still develop against a populated database.

1. **Seed via Docker (recommended)** — applies migrations and inserts catalog, a dev user, two articles, one story, and a `story_rewrites` row (see [`scripts/seed_dev_data.py`](../scripts/seed_dev_data.py)). From the repo root, with dev overrides so `scripts/` is mounted into the web container:

   ```bash
   ./scripts/seed_docker_db.sh
   # Optional: ./scripts/seed_docker_db.sh --skip-sources
   ```

   Docker Compose environment variables (`COMPOSE_FILE`, etc.) are honored. Optional seed env vars: `DEV_EMAIL`, `DEV_PASSWORD` (export them before running so they are passed into the container).

2. **Default login** after seeding: `dev@localhost` / `devpassword` (unless overridden).

3. **Host-side Flask + Docker Postgres only** — with `db` exposing `5432`, set `DATABASE_URL` in `.env`, e.g. `postgresql://dossier:devpassword@localhost:5432/dossier` (see [`.env.example`](../.env.example)). Then:

   ```bash
   alembic upgrade head
   python scripts/seed_dev_data.py
   flask run
   ```

**Dev tools:** Lefthook (git hooks) is a standalone binary; install via your package manager or from [lefthook.dev](https://lefthook.dev). Run `lefthook install` after cloning.

---

## LLM Provider Interface

All LLM access goes through `app/llm/provider.py`. Implementations: `OllamaProvider` (local dev), `VllmOpenAIProvider` (Modal prod), plus optional Gemini/Anthropic.

Config in `config/app.yaml`: `llm.provider`, `llm.model`, `llm.api_base`. Env overrides: `LLM_PROVIDER`, `LLM_API_BASE`, `DOSSIER_LLM_MODEL`, `OPENAI_API_KEY` (vLLM bearer token).

## Embedding Provider

Article clustering uses `app/llm/embeddings.py`: `OllamaEmbeddingProvider` (local dev, `bge-m3`) or `VllmOpenAIEmbeddingProvider` (Modal prod). Env overrides: `EMBED_PROVIDER`, `EMBED_API_BASE`, `EMBED_API_KEY`, `DOSSIER_EMBEDDING_MODEL`.

## Scheduling Model

APScheduler runs in the dedicated `worker` container only (`python -m app.scheduler`). The web container has zero imports from `app/llm/`, `app/feed/`, `app/extraction/`, or `app/clustering/`.

Schedules are defined in [`config/app.yaml`](../config/app.yaml) (see [`PIPELINE.md`](PIPELINE.md) for stage detail):

| Job | Default schedule |
| --- | --- |
| `fetch_feeds` | every 60 min |
| `enrich_articles` | hourly at :05 |
| `check_source_availability` | every 10 min |
| `cluster_articles` | hourly at :15 (embed + cluster) |
| `rewrite_articles` | daily 06:00 (top-10 Catalan digest) |
| `highlight_stories` | hourly at :15 and :45 |

The daily rewrite selects up to `digest.top_n` stories (default 10) and produces a single `neutral/ca` variant. Rewrites are stored in `story_rewrites` and served from the database; no LLM calls during HTTP requests.

### CLI Commands

| Command | Where | Purpose |
| --- | --- | --- |
| `flask seed-sources` | Web container | Seed sources from config |
| `flask make-admin <email>` | Web container | Grant admin access |
| `python -m app.worker_cli fetch-feeds` | Worker | Run feed fetcher once |
| `python -m app.worker_cli enrich-articles` | Worker | Run enrichment once |
| `python -m app.worker_cli cluster-articles` | Worker | Run embed + cluster once |
| `python -m app.worker_cli rewrite-articles` | Worker | Run rewrite batch once |
| `python -m app.worker_cli highlight-stories` | Worker | Run highlight batch once |
| `python -m app.worker_cli rewrite-all-stories` | Worker | Full backfill (operator tooling) |
| `python -m app.worker_cli run-pipeline` | Worker | Full pipeline in one shot |
