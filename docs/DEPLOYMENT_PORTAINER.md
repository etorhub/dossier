# Deployment: NAS via Portainer (UGreen DSP 2800)

This guide deploys the **full Dossier stack** — database, web, worker, and ops
dashboard — as a single Portainer **stack** on the NAS, using the repo's
`docker-compose.yml`. LLM inference (rewriting + embeddings) runs on **Modal GPU
functions** reached over HTTPS; the NAS itself has no GPU and no local Ollama in
this configuration. See [`docs/MODAL_GPU_BACKEND.md`](MODAL_GPU_BACKEND.md) for
the Modal deployment steps — complete those first so you have the endpoint URLs
and API keys to paste into Portainer's environment variables below.

**The NAS pulls prebuilt images, it does not build from source.** GitHub Actions
(`.github/workflows/publish.yml`) builds the `web` and `worker` images on every
push to `main` or `master` (and on `vX.Y.Z` tags) and publishes them to GHCR as
`ghcr.io/etorhub/dossier-web` and `ghcr.io/etorhub/dossier-worker`. The NAS only
pulls — builds no longer compete with the 06:00 inference burst, and you get
immutable, versioned tags you can pin and roll back to. The image tag is selected
with the `DOSSIER_TAG` environment variable (default `latest`).

---

## Architecture

```
UGreen DSP 2800                          Modal (GPU cloud, pay-per-second)
  ├── db       — PostgreSQL 18+pgvector    ├── dossier-rewrite — Qwen2.5-32B-AWQ, L40S GPU
  ├── db-init  — Alembic migrations        └── dossier-embed   — BGE-M3, L4 GPU
  ├── web      — Flask app, port 5000
  ├── worker   — APScheduler pipeline ──────────────────────────────────────────┐
  └── ops      — operator dashboard, port 5001          (HTTPS + bearer auth)   │
                                                                                 │
       worker calls Modal endpoints for every embed + rewrite call ──────────────┘
```

The NAS runs the app stack; Modal runs LLM inference. Both scale to zero — Modal
containers spin up on demand and shut down after idle, so you pay only for the
seconds they're actually computing (roughly 10–20 minutes/day for the daily digest).

---

## Prerequisites

- Portainer CE installed and reachable on the NAS (Container Manager → Portainer, or
  the UGOS Docker app)
- The NAS has internet access to pull `db` images and to reach Modal endpoints at runtime
- At least ~4 GB free RAM and ~5 GB free disk (Postgres data + article cache grow over time)
- **Modal apps deployed** — complete `docs/MODAL_GPU_BACKEND.md` before this step. You
  will need the two `https://*.modal.run/v1` endpoint URLs and the two API keys.

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
# Required — app secrets
POSTGRES_PASSWORD=<choose-a-strong-password>
SECRET_KEY=<generate-with: python3 -c "import secrets; print(secrets.token_hex(32))">

# Required — Modal LLM inference (rewriting)
# Get these from `modal deploy modal/rewrite_server.py` and the Modal dashboard
LLM_PROVIDER=vllm
LLM_API_BASE=https://<your-workspace>--dossier-rewrite-serve.modal.run/v1
OPENAI_API_KEY=<rewrite-bearer-token-from-modal-secret>
# Must match modal/rewrite_server.py's MODEL_NAME (the --served-model-name vLLM
# was started with) — config/app.yaml's default is the Ollama-local tag, not this.
DOSSIER_LLM_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ

# Required — Modal LLM inference (embeddings)
# Get these from `modal deploy modal/embed_server.py`
EMBED_PROVIDER=vllm
EMBED_API_BASE=https://<your-workspace>--dossier-embed-serve.modal.run/v1
EMBED_API_KEY=<embed-bearer-token-from-modal-secret>
# Must match modal/embed_server.py's MODEL_NAME — a mismatch here causes vLLM to
# reject requests with "404 The model `<name>` does not exist."
DOSSIER_EMBEDDING_MODEL=BAAI/bge-m3

# Optional: which published image tag to run. Default is `latest` (newest default-branch
# build). Pin a release for reproducible deploys / rollback, e.g. DOSSIER_TAG=v1.2.0
DOSSIER_TAG=latest

# Optional: host-side port for `db`'s loopback publish (127.0.0.1:<port>:5432).
# Default 5432. Set this if the NAS already runs another Postgres (e.g. another
# stack's db) bound to 127.0.0.1:5432 — otherwise `db` will fail to start with
# "address already in use".
DB_HOST_PORT=5432
```

Never commit these to the repo — they live only in the Portainer stack's environment.

---

## Step 3 — Deploy and watch the first start

Click **Deploy the stack**. Portainer pulls `ghcr.io/etorhub/dossier-web` and
`ghcr.io/etorhub/dossier-worker` at the `DOSSIER_TAG` tag (the first pull is the
slowest app step; subsequent redeploys only pull changed layers). On first start:

1. `db` comes up and passes its healthcheck
2. `db-init` runs Alembic migrations once, then exits (`service_completed_successfully`)
3. `web`, `worker`, and `ops` start once their dependencies are healthy/complete

Watch progress in Portainer: **Stacks → dossier → Containers**, check `worker` logs for
`"Scheduler started"`. There is no Ollama pull step — inference runs on Modal.

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

LLM inference now runs on Modal — the NAS no longer does any model compute during the
06:00 rewrite burst. RAM and CPU pressure from that job are gone. The remaining tuning
knobs:

| Setting | Default | When to change |
|---|---|---|
| gunicorn workers (`web`, `ops`) | default (compose doesn't pin `-w`) | If RAM is tight, add `-w 1` to the service `command` |
| `schedule.rewrite_parallel_workers` (app.yaml) | `1` | Raise to 2–4 once Modal is confirmed working — each worker call is a separate HTTPS request and Modal handles the parallelism |

General guidance:
- Postgres data and job-run logs persist in named volumes/bind mounts — back up
  `pgdata` and `./data/job_runs` before any major Portainer stack recreation
- If the NAS also runs other containers (Plex, etc.), consider `mem_limit:` on db/web
  to cap their RAM; without an Ollama container, peak RAM is much lower than before

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

`db-init` re-runs Alembic migrations safely on every redeploy (idempotent).

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
- **Worker logs LLM errors / rewrites failing**: check that `LLM_PROVIDER`, `LLM_API_BASE`,
  and `OPENAI_API_KEY` are set correctly in Portainer's environment. Verify Modal apps are
  deployed and running: `modal app list` (see `docs/MODAL_GPU_BACKEND.md`).
- **Embeddings failing / clustering job errors**: check `EMBED_PROVIDER`, `EMBED_API_BASE`,
  and `EMBED_API_KEY`. Modal embed app cold-start can take 30–60 s on first call after
  idle — a timeout here is usually a transient retry-able error.
- **Web UI slow on first open**: the worker hasn't completed its first pipeline pass
  yet — run `./scripts/fetch-news.sh` manually (Step 4) to seed content immediately
- **Out of memory**: add `-w 1` to gunicorn commands in the service `command`; without
  Ollama running on the NAS, peak RAM is much lower than before so this should be rare
- **`db` fails to deploy with "failed to bind host port 127.0.0.1:5432: address already in
  use"**: another stack on the NAS (e.g. a different app's Postgres) already holds that
  port. Set `DB_HOST_PORT` (see Step 2) to a free port, e.g. `DB_HOST_PORT=5433`, and
  redeploy — this only changes the host-side publish, not how the app containers reach
  `db` (they always use the internal `db` hostname on the compose network), so no other
  config needs to change.
- **`db-init` fails with `could not translate host name "db" to address: Name or service
  not known`, or `web`/`worker`/`ops` stay stuck in "Created" forever**: usually means `db`
  was recreated outside of a full stack redeploy (e.g. a container-level "Recreate" action)
  and lost its network attachment, so it never joined `dossier_default` — check with
  `docker inspect dossier-db-1 --format '{{json .NetworkSettings.Networks}}'`; `{}` means
  it's not attached. Fix: `docker rm -f dossier-db-1` (safe — data lives in the `pgdata`
  named volume, not the container) and redeploy the whole stack so Compose recreates it
  correctly. If this recurs, check whether **Automatic updates → Polling** is set too
  aggressively (below 15–30 min) for how long the stack takes to start — a poll firing
  mid-startup can repeatedly interrupt the dependency chain.
