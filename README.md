# Dossier

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL 18](https://img.shields.io/badge/PostgreSQL-18-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ed?logo=docker&logoColor=white)](https://www.docker.com/)
[![HTMX](https://img.shields.io/badge/HTMX-2.x-3d7fcf?logo=htmx&logoColor=white)](https://htmx.org/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama_local-000000)](https://ollama.ai/)

A personal daily news digest — curated, rewritten in Catalan, delivered once a day.

Once a day at 06:00, the pipeline scores all clustered stories, picks the 10 most relevant, rewrites them in clean Catalan, and sends a push notification: "El teu dossier d'avui és aquí". Open the app, read 10 well-written stories in ~5 minutes, and you're done.

---

## What It Does

- Fetches news from RSS feeds and open publishers continuously (Catalan and Spanish sources)
- Clusters articles from different outlets covering the same event into a single story
- Every morning at 06:00: selects the 10 most relevant stories (by recency and multi-source coverage), rewrites them via LLM in Catalan, and sends a push notification
- Presents the daily digest in a clean, accessible interface with large fonts, high contrast, and large touch targets
- Provides text-to-speech when the browser supports it
- Content is ready when you open the app — no waiting, no loading screens

## Who It's For

A personal tool for anyone who wants a quick, clean daily briefing. Designed to run on a home NAS (UGreen DSP 2800) with Ollama running locally. One instance, one digest, one language.

Neither the user nor anyone setting up the instance ever touches the codebase. Setup is done through the web app.

---

## Quick Start

### Prerequisites

- Docker and docker-compose

### Setup

The **Ollama** service is optional in Compose (profile `local-llm`). Clustering, embeddings, and rewrites need a reachable Ollama. [`.env.example`](.env.example) sets `COMPOSE_PROFILES=local-llm` so a copied `.env` starts Ollama in Docker and runs **`ollama-init`** once per `up` (pulls `qwen2.5:3b`, `bge-m3` into the `ollama_data` volume). The **worker** waits for that init to finish before running. Model pull happens at **container start**, not during `docker build`.

**NAS deployment** (UGreen DSP 2800 or similar, CPU only):

```bash
git clone https://github.com/etorhub/dossier.git
cd dossier
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.nas.yml up --build -d
```

**With Ollama in Docker** (generic, no GPU):

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build -d
```

Without a `.env`, pass the profile explicitly: `docker compose --profile local-llm up --build -d`.

**Ollama on the host instead** (e.g. already running `ollama serve`): remove or comment out `COMPOSE_PROFILES=local-llm` in `.env`, pull the same model tags on the host (`ollama pull qwen2.5:3b bge-m3`), and set `OLLAMA_HOST` for the worker. See [`.env.example`](.env.example).

Wait for services to be healthy (web at `http://localhost:5000`, worker running, **ollama** healthy if you use the profile). Then populate with news:

```bash
./scripts/fetch-news.sh
```

The script fetches feeds, extracts full text, clusters articles, and rewrites them. When it finishes, the app has real content.

### Ops dashboard

Operators can monitor the pipeline at the **ops dashboard**: `http://localhost:5001`. It shows job runs, feed health, source availability, articles, stories, and user activity. No authentication by default (restrict access at the network level).

```bash
docker compose up -d ops
```

### Admin account

A default admin is ready to use: **admin@admin.com** / **admin**. Log in to access the app.

To grant admin privileges to another user (for future use):

```bash
docker compose exec web flask make-admin your@email.com
```

See [docs/ADMIN_DASHBOARD.md](docs/ADMIN_DASHBOARD.md) for ops dashboard documentation.

### Manual pipeline control

The scheduler runs jobs on a schedule. To run them manually:

| Command | Where | Description |
| ------- | ----- | ----------- |
| `flask seed-sources` | Web | Load sources from config/sources.yaml (auto-run on startup) |
| `python -m app.worker_cli fetch-feeds` | Worker | Fetch all due RSS feeds |
| `python -m app.worker_cli enrich-articles` | Worker | Extract full article content for pending articles |
| `python -m app.worker_cli cluster-articles` | Worker | Embed and cluster today's articles |
| `python -m app.worker_cli rewrite-articles` | Worker | Rewrite articles for all user profiles |
| `python -m app.worker_cli rewrite-all-stories` | Worker | Regenerate **all** story rewrites (full cascade); for prompt/model tuning — see [docs/TECH_STACK.md](docs/TECH_STACK.md#full-story-rewrite-backfill-rewrite-all-stories) |
| `python -m app.worker_cli run-pipeline` | Worker | Full pipeline once (seed → fetch → enrich → cluster → rewrite) |

With Docker:

```bash
docker compose exec worker python -m app.worker_cli run-pipeline
```

Or use `./scripts/fetch-news.sh` for the same result.

### Running locally (without Docker)

```bash
# Requires Python 3.12+ and a running PostgreSQL instance
pip install -r requirements.txt
flask run
```

---

## Tech Stack

| Layer      | Technology                                  |
| ---------- | ------------------------------------------- |
| Backend    | Python 3.12+ / Flask                        |
| Database   | PostgreSQL 18                               |
| LLM        | Ollama (local, no API key)                  |
| Frontend   | HTML + CSS + HTMX (no JavaScript frameworks) |
| Scheduling | APScheduler (worker container)               |
| Packaging  | Docker + docker-compose                     |

See [docs/TECH_STACK.md](docs/TECH_STACK.md) for full details.

---

## Documentation

| Document                                                                   | Description                                                                                                                           |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| [CONTRIBUTING.md](CONTRIBUTING.md)                                         | How to contribute — setup, code standards, commits, PRs                                                                                |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)                                   | Community standards and enforcement                                                                                                   |
| [SECURITY.md](SECURITY.md)                                                 | Security policy and vulnerability reporting                                                                                           |
| [CLAUDE.md](CLAUDE.md)                                                     | AI assistant context (Claude Code) — coding rules, architecture constraints, design principles                                        |
| [.cursor/rules/](.cursor/rules/)                                           | Cursor IDE rules — same context via `project-context.mdc` (always apply) plus architecture, accessibility, LLM, news-source-discovery |
| [docs/TECH_STACK.md](docs/TECH_STACK.md)                                   | Tech stack, project structure, dependencies, Docker setup                                                                             |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)                               | System architecture, database schema, component map, request lifecycle                                                                |
| [docs/ADMIN_DASHBOARD.md](docs/ADMIN_DASHBOARD.md)                         | Ops dashboard: pipeline monitoring, job history, source availability, user activity, incidents                                         |
| [docs/I18N.md](docs/I18N.md)                                               | Internationalization: locale selection, translation catalogs, updating strings                                                       |
| [docs/MVP_PLAN.md](docs/MVP_PLAN.md)                                       | Phased MVP plan with tasks and success criteria                                                                                       |
| [docs/news_source_discovery_agent.md](docs/news_source_discovery_agent.md) | News source discovery pipeline specification                                                                                          |

---

## Accessibility

Accessibility is a constraint, not a feature. Good defaults benefit all users:

- Minimum 48x48px touch targets on all interactive elements
- Base font size 22px, line height 1.6
- WCAG AA contrast minimum (4.5:1), AAA target (7:1) in high-contrast mode
- One article at a time — no infinite scroll
- Text-to-speech via Web Speech API (hidden when not supported)
- Semantic HTML throughout
- No hover-only interactions, no timed content

---

## License

AGPL-3.0. See [LICENSE](LICENSE) for details.

The project is a reading aid, not a republisher. Every article links to and credits the original source. Copyright remains with the publisher.
