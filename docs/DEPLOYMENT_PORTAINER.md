# Deployment: NAS via Portainer (UGreen DSP 2800)

This guide deploys the **full Dossier stack** — database, web, worker, ops dashboard,
and a local Ollama (CPU inference) — as a single Portainer **stack** on the NAS,
using the repo's `docker-compose.yml`. The compose file is the single source of
truth for this deployment: it's already tuned for CPU-only inference and low RAM
(no GPU, no separate NAS override file — there's only one deployment target).

---

## Architecture (single NAS, one stack)

```
UGreen DSP 2800
  ├── db          — PostgreSQL 18 + pgvector
  ├── ollama      — qwen2.5:3b (rewrite) + paraphrase-multilingual (embeddings), CPU only
  ├── ollama-init — one-shot model pull, runs once on first start
  ├── db-init     — one-shot Alembic migration, runs once on first start
  ├── web         — Flask app, port 5000
  ├── worker      — APScheduler pipeline (fetch → enrich → embed → cluster → rewrite)
  └── ops         — operator dashboard, port 5001
```

Everything runs on the NAS — no external services, no GPU, no second machine.

---

## Prerequisites

- Portainer CE installed and reachable on the NAS (Container Manager → Portainer, or
  the UGOS Docker app)
- The NAS has internet access to build the app image and pull `db`/`ollama` images
- At least ~6 GB free RAM and ~10 GB free disk (Postgres data + Ollama models +
  article cache grow over time)

---

## Step 1 — Create the stack from the Git repository

The `web`, `worker`, `db-init`, and `ops` services are built from the repo's
`Dockerfile` (`build: context: .`). **Portainer's Web editor mode has no source
checkout, so `build:` directives fail with "Dockerfile: no such file or
directory"** — you must use the **Repository** build method, which clones the repo
first.

In Portainer:

1. **Stacks → Add stack**
2. Name it `dossier`
3. Build method: **Repository**
   - Repository URL: `https://github.com/etorhub/dossier`
   - Repository reference: `refs/heads/master`
   - Compose path: `docker-compose.yml`

---

## Step 2 — Environment variables

In the stack's **Environment variables** section, add:

```bash
# Required
POSTGRES_PASSWORD=<choose-a-strong-password>
SECRET_KEY=<generate-with: python3 -c "import secrets; print(secrets.token_hex(32))">

# Starts Ollama in this stack (profile local-llm)
COMPOSE_PROFILES=local-llm
OLLAMA_HOST=http://ollama:11434
```

Never commit these to the repo — they live only in the Portainer stack's environment.

---

## Step 3 — Deploy and watch the first start

Click **Deploy the stack**. Since Portainer clones the repo, the `Dockerfile` is
present and the `build:` directives for `web`, `worker`, `db-init`, and `ops`
resolve correctly. On first start:

1. `db` comes up and passes its healthcheck
2. `db-init` runs Alembic migrations once, then exits (`service_completed_successfully`)
3. `ollama` starts in CPU mode (`OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`
   — one model resident at a time, since the daily job never runs rewrite and
   embedding concurrently)
4. `ollama-init` pulls `qwen2.5:3b` and `paraphrase-multilingual` (~2–3 GB total) — the slowest step
   on first run, expect 10–30 minutes depending on NAS bandwidth/disk speed — then exits
5. `web`, `worker`, and `ops` start once their dependencies are healthy/complete

Watch progress in Portainer: **Stacks → dossier → Containers**, check logs on
`ollama-init` for pull progress, and on `worker` for `"waiting for ollama-init"` →
`"Scheduler started"`.

---

## Step 4 — First-run setup

Once `web` is healthy:

1. Open `http://<nas-ip>:5000`, create the admin account, and complete the setup
   wizard (topics, sources, rewrite tone)
2. Open the ops dashboard at `http://<nas-ip>:5001` to confirm feed health and job runs
3. Trigger an initial fetch so the app has content immediately instead of waiting for
   the next scheduled run:

   ```bash
   docker exec -it <worker-container-name> ./scripts/fetch-news.sh
   ```

   (find the exact container name in Portainer's container list, e.g. `dossier-worker-1`)

The daily pipeline then runs unattended: fetch → enrich → embed → cluster
continuously, and the 06:00 job selects the top 10 stories and rewrites them in
Catalan, ready to read when you open the app.

---

## Performance tuning for the DSP 2800

`docker-compose.yml` already applies the safe defaults below. Adjust only if you
observe resource pressure (Portainer → container stats, or the NAS's own resource monitor):

| Setting | Default | When to change |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | Raise to `2` only if RAM ≥ 16 GB and rewrites feel slow |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Keep at `1` — embedding and rewriting never run concurrently in the daily job |
| gunicorn workers (`web`, `ops`) | default (compose doesn't pin `-w`) | If RAM is tight, edit the service `command` to add `-w 1` |

General guidance:
- `qwen2.5:3b` is the right model for 10 stories/day on CPU — it's the only model
  this deployment pulls and uses
- Postgres, Ollama, and the article/job-run data all persist in named volumes/bind
  mounts — back up `pgdata`, `ollama_data`, and `./data/job_runs` before any major
  Portainer stack recreation
- If the NAS also runs other containers (Plex, etc.), consider setting per-service
  memory limits in the compose (`mem_limit:`) so Dossier can't starve them during the
  06:00 rewrite burst

---

## Updating the stack

With the **Repository** build method, Portainer can poll the `master` branch and
redeploy automatically (enable "Automatic updates" / webhook on the stack), rebuilding
the images from the updated `Dockerfile` and re-running `docker-compose.yml`.

`db-init` re-runs Alembic migrations safely on every redeploy (idempotent), and
`ollama-init` only pulls models that aren't already present in the `ollama_data` volume.

---

## Troubleshooting

- **"failed to read dockerfile: open Dockerfile: no such file or directory"**: you're
  using the Web editor build method — switch to **Repository** (Step 1); Portainer
  needs the cloned source tree to build `web`/`worker`/`ops`/`db-init`
- **`ollama-init` stuck / failing to pull**: check NAS internet connectivity and disk
  space (`docker system df`); model pulls need ~5 GB free during download+extraction
- **`worker` logs `waiting for ollama-init`**: normal on first start — wait for the
  pull to finish; subsequent restarts skip this since models persist in `ollama_data`
- **Web UI slow on first open**: the worker hasn't completed its first pipeline pass
  yet — run `./scripts/fetch-news.sh` manually (Step 4) to seed content immediately
- **Out of memory**: `OLLAMA_NUM_PARALLEL`/`OLLAMA_MAX_LOADED_MODELS` are already at
  the minimum (`1`); add `-w 1` to gunicorn commands, or check for other containers
  competing for RAM during the 06:00 rewrite window
