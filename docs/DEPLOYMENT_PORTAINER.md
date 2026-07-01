# Deployment: NAS via Portainer (UGreen DSP 2800)

This guide deploys the **full Dossier stack** — database, web, worker, ops dashboard,
and a local Ollama (CPU inference) — as a single Portainer **stack** on the NAS,
using the repo's `docker-compose.yml`.

> **Model note:** the default `docker-compose.yml` targets a local GPU machine
> (`qwen2.5:14b` + `bge-m3`). For the NAS (CPU-only) you **must** add
> `DOSSIER_LLM_MODEL=qwen2.5:3b` to the Portainer stack environment — this
> overrides the rewrite model without changing any files. `bge-m3` runs on
> CPU too (~30s/article), so no override needed for embeddings.

**The NAS pulls prebuilt images, it does not build from source.** GitHub Actions
(`.github/workflows/publish.yml`) builds the `web` and `worker` images on every
push to `main` or `master` (and on `vX.Y.Z` tags) and publishes them to GHCR as
`ghcr.io/etorhub/dossier-web` and `ghcr.io/etorhub/dossier-worker`. The NAS only
pulls — builds no longer compete with the 06:00 inference burst, and you get
immutable, versioned tags you can pin and roll back to. The image tag is selected
with the `DOSSIER_TAG` environment variable (default `latest`).

---

## Architecture (single NAS, one stack)

```
UGreen DSP 2800
  ├── db          — PostgreSQL 18 + pgvector
  ├── ollama      — qwen2.5:3b (rewrite, via DOSSIER_LLM_MODEL override) + bge-m3 (embeddings), CPU only
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

Use the **Repository** build method so the `docker-compose.yml` stays
version-controlled in git — Portainer clones the repo to read the compose file.
The services reference prebuilt `image:` tags (no `build:` directives), so Portainer
**pulls** `web`/`worker` images from GHCR rather than building them on the NAS.

In Portainer:

1. **Stacks → Add stack**
2. Name it `dossier`
3. Build method: **Repository**
   - Repository URL: `https://github.com/etorhub/dossier`
   - Repository reference: `refs/heads/main` (the repo's default branch — use
     whichever branch you actually merge to; `main` and `master` both build images)
   - Compose path: `docker-compose.yml`

The GHCR images are public (the repo is AGPL/public), so no registry credentials
are needed. If you later make the packages private, add a registry under
**Portainer → Registries** with a GitHub PAT scoped to `read:packages`.

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

# NAS model override — the default config targets a GPU machine (qwen2.5:14b).
# This tells ollama-init to pull qwen2.5:3b instead, and tells the worker to use it.
DOSSIER_LLM_MODEL=qwen2.5:3b

# Optional: which published image tag to run. Default is `latest` (newest default-branch
# build). Pin a release for reproducible deploys / rollback, e.g. DOSSIER_TAG=v1.2.0
DOSSIER_TAG=latest
```

Never commit these to the repo — they live only in the Portainer stack's environment.

---

## Step 3 — Deploy and watch the first start

Click **Deploy the stack**. Portainer pulls `ghcr.io/etorhub/dossier-web` and
`ghcr.io/etorhub/dossier-worker` at the `DOSSIER_TAG` tag (the first pull is the
slowest app step; subsequent redeploys only pull changed layers). On first start:

1. `db` comes up and passes its healthcheck
2. `db-init` runs Alembic migrations once, then exits (`service_completed_successfully`)
3. `ollama` starts in CPU mode (`OLLAMA_NUM_PARALLEL=2`, `OLLAMA_MAX_LOADED_MODELS=1`
   — one model resident at a time, since the daily job never runs rewrite and
   embedding concurrently)
4. `ollama-init` pulls `qwen2.5:3b` (via `DOSSIER_LLM_MODEL`) and `bge-m3` (~2.5 GB total)
   — the slowest step on first run; expect 10–30 min depending on NAS bandwidth — then exits
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
| `DOSSIER_LLM_MODEL` | `qwen2.5:3b` (set in Portainer env) | Leave at `qwen2.5:3b` for the NAS — do not pull `qwen2.5:14b` on CPU |
| `OLLAMA_NUM_PARALLEL` | `2` | Lower to `1` if RAM is tight and rewrites contend |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Keep at `1` — embedding and rewriting never run concurrently in the daily job |
| gunicorn workers (`web`, `ops`) | default (compose doesn't pin `-w`) | If RAM is tight, edit the service `command` to add `-w 1` |

General guidance:
- `qwen2.5:3b` (via `DOSSIER_LLM_MODEL` override) is the right model for 10 stories/day on CPU
- `bge-m3` works fine on CPU at ~30s/article — only ~10–20 articles need embedding per day at steady state
- Postgres, Ollama, and the article/job-run data all persist in named volumes/bind
  mounts — back up `pgdata`, `ollama_data`, and `./data/job_runs` before any major
  Portainer stack recreation
- If the NAS also runs other containers (Plex, etc.), consider setting per-service
  memory limits in the compose (`mem_limit:`) so Dossier can't starve them during the
  06:00 rewrite burst

---

## Updating the stack

The pipeline is: **push to `main` → GitHub Actions builds and publishes new images
to GHCR → the NAS pulls and redeploys.** The NAS never builds.

**Recommended: polling + re-pull (no inbound access to the NAS required).** On the
stack, enable **Automatic updates → Polling**, and make sure **"Re-pull image"** is
on. Portainer then periodically checks both the git repo (for compose changes) and
the registry (for a newer image at the `DOSSIER_TAG` tag), and redeploys when either
moves. This works behind a home router/NAT with no port-forwarding or tunnel — the
only cost is that a deploy lands within the poll interval rather than instantly,
which is fine for a once-a-day digest.

> A **webhook** (Portainer generates a URL that Actions `curl`s after publishing) is
> faster but needs Portainer to be reachable *from GitHub* — i.e. a Cloudflare Tunnel,
> reverse proxy, or VPN exposing the NAS. Not worth the added exposure for this
> single-user tool; polling is the better fit.

**Pinning and rolling back.** Because images are versioned, you control exactly what
runs via `DOSSIER_TAG`:

- Leave `DOSSIER_TAG=latest` to always track the newest default-branch build, **or**
- Set `DOSSIER_TAG=v1.2.0` (a tagged release) or `DOSSIER_TAG=sha-abc1234` (an exact
  commit) for a reproducible deploy.
- **Roll back** by editing `DOSSIER_TAG` to a known-good tag and redeploying — seconds,
  no rebuild. (Available tags are listed under the repo's **Packages** on GitHub.)

`db-init` re-runs Alembic migrations safely on every redeploy (idempotent), and
`ollama-init` only pulls models that aren't already present in the `ollama_data` volume.

> **Migrations and rollback:** rolling the image back does **not** roll back the
> database. Alembic migrations are forward-only here, so a rollback is safe only to a
> tag whose schema matches the current DB. If a release added a migration, downgrade
> the schema first (or restore a `pgdata` backup) before pinning an older image.

---

## Troubleshooting

- **`manifest unknown` / `pull access denied` for `ghcr.io/etorhub/dossier-*`**: the
  tag in `DOSSIER_TAG` doesn't exist yet (no published build for it — check the repo's
  **Packages**), or the package was made private (add a GHCR registry with a
  `read:packages` PAT under **Portainer → Registries**). The very first deploy must
  wait for `publish.yml` to have run at least once on `main`.
- **Stack not updating after a push**: confirm **Automatic updates → Polling** is on
  with **"Re-pull image"** enabled, and that `publish.yml` succeeded for that commit
  (repo → **Actions**). Polling only redeploys once the new image is actually in GHCR.
- **`ollama-init` stuck / failing to pull**: check NAS internet connectivity and disk
  space (`docker system df`); model pulls need ~5 GB free during download+extraction
- **`worker` logs `waiting for ollama-init`**: normal on first start — wait for the
  pull to finish; subsequent restarts skip this since models persist in `ollama_data`
- **Web UI slow on first open**: the worker hasn't completed its first pipeline pass
  yet — run `./scripts/fetch-news.sh` manually (Step 4) to seed content immediately
- **Out of memory**: `OLLAMA_NUM_PARALLEL`/`OLLAMA_MAX_LOADED_MODELS` are already at
  the minimum (`1`); add `-w 1` to gunicorn commands, or check for other containers
  competing for RAM during the 06:00 rewrite window
