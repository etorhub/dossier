# Tech Stack

Technology choices for Dossier, with rationale.

---

## Core Stack

| Layer | Technology | Why |
| --- | --- | --- |
| Backend | Python 3.12+ with Flask | Lightweight, well-understood, Jinja2 built-in |
| Database | PostgreSQL 18 | Robust, multi-user, JSONB support, wide hosting availability |
| LLM | Ollama (local) or OpenAI-compatible HTTP (vLLM) via provider interface | Local inference; defaults: `qwen2.5:7b` (rewrite), `qwen2.5:3b` (simplify/translate), `nomic-embed-text` embeddings |
| Frontend | Plain HTML + CSS + HTMX | No build step, no JS framework, server-rendered throughout |
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
│   │   ├── embeddings.py    # Embedding provider (Ollama nomic-embed-text)
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

Five services: PostgreSQL, Ollama (LLM/embeddings), the Flask web app (slim image), the worker (feed processing + ollama client), and the ops dashboard.

- **ollama** — Runs Ollama server. Models (`qwen2.5:7b`, `qwen2.5:3b`, `nomic-embed-text`) are pulled on first start via `ollama-init`. `OLLAMA_NUM_PARALLEL=4` is set so concurrent rewrite jobs share the GPU. GPU is the default; use `docker-compose.cpu.yml` for CPU-only systems.
- **web** — Gunicorn serves the Flask app. Uses `requirements-web.txt` (no ollama, no feed processing). Runs `alembic upgrade head` on startup, then Gunicorn.
- **worker** — Runs APScheduler (`python -m app.scheduler`) for scheduled pipeline jobs (fetch, enrich, cluster, rewrite, check_source_availability). Uses `requirements.txt` (includes ollama Python client). Connects to ollama service for LLM and embeddings. Processing CLI commands run here: `docker compose exec worker python -m app.worker_cli fetch-feeds`, etc.
- **ops** — Separate Flask app for operators. Serves the ops dashboard at port 5001. Uses the same database; no auth by default.

**Hybrid Pi + PC:** To run Postgres, the web app, and light jobs on a small board (e.g. Raspberry Pi) while Ollama and embedding/cluster/rewrite jobs run on another machine, set `SCHEDULER_MODE` (`light` / `heavy` / `full`) and see [docs/DEPLOYMENT_HYBRID.md](DEPLOYMENT_HYBRID.md).

```yaml
# docker-compose.yml (simplified)
services:
  ollama:
    image: ollama/ollama
    volumes:
      - ollama_data:/root/.ollama
    # ...

  db:
    image: postgres:18-alpine
    # ...

  web:
    build:
      context: .
      target: web
    ports:
      - "5000:5000"
    command: sh -c "alembic upgrade head && gunicorn -b 0.0.0.0:5000 app:application"

  worker:
    build:
      context: .
      target: worker
    depends_on:
      db:
        condition: service_healthy
      ollama-init:
        condition: service_completed_successfully
        required: false  # omitted when local-llm profile is off (host Ollama)
    environment:
      OLLAMA_HOST: http://ollama:11434
    command: python -m app.scheduler
    # ...

  ops:
    build:
      context: .
      target: web
    ports:
      - "5001:5001"
    command: gunicorn -b 0.0.0.0:5001 ops:application
    # ...
```

`docker-compose.override.yml` provides dev overrides: bind mounts for live reload, `flask run --debug` for the web service, exposed ports, and **Postgres published on `localhost:5432`** so you can run `flask run` on the host or connect with `psql`. The `.env` file contains the database password. No LLM API keys required. An `.env.example` template is provided in the repo.

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

### GPU troubleshooting (Ollama using CPU instead of GPU)

If Ollama uses high CPU but negligible GPU utilization:

1. **Verify GPU inside container:**
   ```bash
   docker compose exec ollama nvidia-smi
   ```
   If this fails, the GPU is not passed to the container. On CPU-only systems, use `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up`.

2. **Check Ollama logs for GPU detection:**
   ```bash
   docker compose logs ollama
   ```
   Look for "Nvidia GPU" or "CUDA" — or errors like "no compatible GPUs", "cudart", "libcuda".

3. **WSL2 + Docker Desktop:** Add the NVIDIA runtime to Docker Engine (Settings → Docker Engine):
   ```json
   "runtimes": {
     "nvidia": {
       "path": "nvidia-container-runtime",
       "runtimeArgs": []
     }
   }
   ```
   Then restart Docker Desktop.

4. **NVIDIA Container Toolkit:** On Linux/WSL2, install:
   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure
   ```

5. **Recreate ollama container:**
   ```bash
   docker compose down ollama
   docker compose up -d
   ```

---

## LLM Provider Interface

The app never calls Ollama directly. All LLM access goes through `app/llm/provider.py`, which defines an abstract `LLMProvider` class. Implementations include `OllamaProvider` (default), Gemini, Anthropic, and `VllmOpenAIProvider` for any OpenAI-compatible HTTP server (e.g. vLLM, SGLang). Config in `config/app.yaml`: `llm.provider` (`ollama` \| `vllm` \| …), `llm.model`, `llm.host` (Ollama default `http://ollama:11434`). For `llm.provider: vllm`, set `llm.api_base` to the server’s OpenAI root (e.g. `http://localhost:8000/v1`). Per-task models for the rewrite cascade: `rewrite_model`, `simplify_model`, `translate_model` (each falls back to `model` when unset). Defaults use `qwen2.5:7b` for rewrite and `qwen2.5:3b` for simplify/translate. No API key required for Ollama.

Rewrite throughput: `schedule.rewrite_parallel_workers` runs multiple stories concurrently; each story parallelizes translation steps. Align with Ollama’s `OLLAMA_NUM_PARALLEL` (see `docker-compose.yml`). Benchmark: `python scripts/benchmark_rewrite_llm.py --help`.

## Embedding Provider

Article clustering uses embeddings for similarity via **Ollama** (`nomic-embed-text`). Config: `embeddings.model`, `embeddings.host`. No API key required.

---

## Scheduling Model

APScheduler runs in the dedicated `worker` container only (`python -m app.scheduler`). It is never started inside the `web` container. The web container has zero imports from `app/llm/`, `app/feed/`, `app/extraction/`, or `app/clustering/` — it is a thin HTTP layer.

Background jobs in the worker:

1. **Fetch jobs** — poll feeds per their configured interval. Articles are stored in the `articles` table.
2. **Enrichment jobs** — extract full article text from URLs (Trafilatura) for articles with `extraction_status = 'pending'`.
3. **Cluster jobs** — embed articles (Ollama nomic-embed-text), complete-linkage cosine similarity grouping, create story records only for groups with ≥2 distinct sources covering the same event.
4. **Rewrite jobs** — run at a configurable daily time (default: 06:00). Uses a cascading pipeline: generate neutral English from sources, simplify to simple English, then translate both to other languages (translations may run in parallel within a story; multiple stories may run in parallel). Per-task models (`rewrite_model`, `simplify_model`, `translate_model`) can be tuned in config. Rewrites are stored in `story_rewrites` and shared across all users with the same `(style, language)` variant.
5. **Availability check** — runs every 10 minutes (configurable). HTTP HEAD/GET to each active feed; stores results in `source_availability_checks`. Visible in the ops dashboard.

When a user opens the app, content is already ready. No waiting.

### CLI Commands

| Command | Where | Purpose |
| --- | --- | --- |
| `flask seed-sources` | Web container | Seed sources from config (lightweight) |
| `flask make-admin <email>` | Web container | Grant admin access |
| `flask show-rewrite-failures` | Web container | List recent rewrite failures (DB read) |
| `python -m app.worker_cli fetch-feeds` | Worker container | Run feed fetcher once |
| `python -m app.worker_cli enrich-articles` | Worker container | Run enrichment once |
| `python -m app.worker_cli cluster-articles` | Worker container | Run clustering once |
| `python -m app.worker_cli rewrite-articles` | Worker container | Run rewrite batch once |
| `python -m app.worker_cli run-pipeline` | Worker container | Full pipeline: seed → fetch → enrich → cluster → rewrite |
