# Deployment: NAS via Portainer (UGreen DSP 2800)

This guide deploys Dossier's **NAS half** — database, web, worker, and ops
dashboard — as a single Portainer **stack** on the NAS, using the repo's
`docker-compose.yml`.

> **No Ollama on the NAS.** The NAS worker runs "light": it fetches feeds,
> enriches full text, and checks source availability, but runs **none** of the
> LLM stages (embed, cluster, rewrite, highlight) and no Ollama. Those run
> off-host on an on-demand GPU (Modal free tier, or a local/VPS box) against this
> same Postgres over a Cloudflare Tunnel — see
> [`docs/REMOTE_REWRITE.md`](REMOTE_REWRITE.md) and [`deploy/modal/`](../deploy/modal/).
> Set `DOSSIER_LLM_JOBS_ENABLED=false` in the Portainer stack environment (below)
> to enable light mode.
>
> Consequence: the NAS can't produce the digest on its own, so the off-host
> runner is **required daily** for fresh content (the Modal Cron handles this).

**The NAS pulls prebuilt images, it does not build from source.** GitHub Actions
(`.github/workflows/publish.yml`) builds the `web` and `worker` images on every
push to `main` or `master` (and on `vX.Y.Z` tags) and publishes them to GHCR as
`ghcr.io/etorhub/dossier-web` and `ghcr.io/etorhub/dossier-worker`. The NAS only
pulls — no build load on the NAS, and you get
immutable, versioned tags you can pin and roll back to. The image tag is selected
with the `DOSSIER_TAG` environment variable (default `latest`).

---

## Architecture (NAS stack + off-host LLM runner)

```
UGreen DSP 2800 (CPU-only, no Ollama)
  ├── db          — PostgreSQL 18 + pgvector
  ├── db-init     — one-shot Alembic migration, runs once on first start
  ├── web         — Flask app, port 5000
  ├── worker      — APScheduler, LIGHT: fetch → enrich → availability only
  └── ops         — operator dashboard, port 5001

Off-host runner (Modal free-tier GPU / local / VPS), daily:
  └── embed + cluster → rewrite → highlight  (Ollama runs here, on GPU)
        └── connects to db over a Cloudflare Tunnel (scoped dossier_pipeline role)
```

The NAS does the light, always-on work (keeping the article store fresh); the
GPU-heavy LLM stages run elsewhere on a schedule. See
[`docs/REMOTE_REWRITE.md`](REMOTE_REWRITE.md) for the off-host setup and
[`deploy/modal/`](../deploy/modal/) for the primary Modal runner.

---

## Prerequisites

- Portainer CE installed and reachable on the NAS (Container Manager → Portainer, or
  the UGOS Docker app)
- The NAS has internet access to pull the `db`, `web`, and `worker` images from GHCR
- At least ~3 GB free RAM and ~10 GB free disk (Postgres data + article cache grow
  over time; no Ollama models are stored on the NAS)

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

# Light worker: run only the non-LLM stages (fetch/enrich/availability) here and
# no Ollama. The LLM stages run off-host — see docs/REMOTE_REWRITE.md.
DOSSIER_LLM_JOBS_ENABLED=false

# Optional: which published image tag to run. Default is `latest` (newest default-branch
# build). Pin a release for reproducible deploys / rollback, e.g. DOSSIER_TAG=v1.2.0
DOSSIER_TAG=latest
```

> Do **not** set `COMPOSE_PROFILES=local-llm` on the NAS — that profile starts
> Ollama, which the NAS no longer runs. Leaving it unset keeps the `ollama` and
> `ollama-init` services out of the stack entirely. `DOSSIER_LLM_MODEL` /
> `OLLAMA_HOST` are likewise unnecessary here.

Never commit these to the repo — they live only in the Portainer stack's environment.

---

## Step 3 — Deploy and watch the first start

Click **Deploy the stack**. Portainer pulls `ghcr.io/etorhub/dossier-web` and
`ghcr.io/etorhub/dossier-worker` at the `DOSSIER_TAG` tag (the first pull is the
slowest step; subsequent redeploys only pull changed layers). On first start:

1. `db` comes up and passes its healthcheck
2. `db-init` runs Alembic migrations once, then exits (`service_completed_successfully`)
3. `web`, `worker`, and `ops` start once `db-init` completes

There is no Ollama service and no model pull, so the stack is ready in the time it
takes to pull images and migrate — no 10–30 min model download.

Watch progress in Portainer: **Stacks → dossier → Containers**, and check the
`worker` log for `"Scheduler started (light): ... LLM stages ... are disabled
here"` — that confirms light mode is active.

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

The NAS worker then runs unattended: fetch → enrich → availability continuously,
keeping the article store fresh. The LLM stages (embed → cluster → rewrite →
highlight) that turn those articles into the daily digest run **off-host** — set
that up next in [`docs/REMOTE_REWRITE.md`](REMOTE_REWRITE.md) (primary runner:
[`deploy/modal/`](../deploy/modal/)). Until the off-host runner has run once,
the app has fetched articles but no rewritten digest.

---

## Performance tuning for the DSP 2800

Without Ollama on the NAS, the stack is light — the worker only fetches, enriches,
and checks availability. Adjust only if you observe resource pressure (Portainer →
container stats, or the NAS's own resource monitor):

| Setting | Default | When to change |
|---|---|---|
| `DOSSIER_LLM_JOBS_ENABLED` | `false` (set in Portainer env) | Keep `false` on the NAS — the LLM stages run off-host, not on this CPU |
| gunicorn workers (`web`, `ops`) | default (compose doesn't pin `-w`) | If RAM is tight, edit the service `command` to add `-w 1` |

General guidance:
- No model download and no GPU/CPU inference burst on the NAS — the heavy work is
  offloaded, so the DSP 2800 stays comfortably within its RAM budget.
- Postgres and the article/job-run data persist in a named volume / bind mount —
  back up `pgdata` and `./data/job_runs` before any major Portainer stack recreation.
  (There is no `ollama_data` volume to back up on the NAS anymore.)
- If the NAS also runs other containers (Plex, etc.), the light worker is unlikely
  to contend for RAM, but you can still set per-service `mem_limit:` in the compose.

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
- **`worker` log shows the LLM jobs still registered / it tries to reach Ollama**:
  `DOSSIER_LLM_JOBS_ENABLED=false` isn't set — add it to the stack env and redeploy.
  The log should read `"Scheduler started (light): ..."`.
- **Articles appear but no rewritten digest**: expected — the LLM stages run off-host.
  Confirm the off-host runner has run (Modal schedule / `run-remote-pipeline.sh`) and
  check its `job_runs` rows on the ops dashboard. See [`docs/REMOTE_REWRITE.md`](REMOTE_REWRITE.md).
- **Web UI slow / empty on first open**: the worker hasn't completed its first fetch
  pass yet — run `./scripts/fetch-news.sh` manually (Step 4) to seed content immediately.
- **Out of memory**: unlikely without Ollama; add `-w 1` to the `web`/`ops` gunicorn
  commands, or check for other containers competing for RAM.
