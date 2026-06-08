# Deployment: NAS via Portainer (UGreen DSP 2800)

This guide deploys the **full Dossier stack** — database, web, worker, ops dashboard,
and a local Ollama (CPU inference) — as a single Portainer **stack** on the NAS.
It uses the existing `docker-compose.yml` + `docker-compose.nas.yml` override, which
is already tuned for low-RAM, CPU-only hardware.

---

## Architecture (single NAS, one stack)

```
UGreen DSP 2800
  ├── db        — PostgreSQL 18 + pgvector
  ├── ollama    — qwen2.5:3b (rewrite) + bge-m3 (embeddings), CPU only
  ├── ollama-init — one-shot model pull, runs once on first start
  ├── db-init   — one-shot Alembic migration, runs once on first start
  ├── web       — Flask app, port 5000
  ├── worker    — APScheduler pipeline (fetch → enrich → embed → cluster → rewrite)
  └── ops       — operator dashboard, port 5001
```

Everything runs on the NAS; no external services required (Neon/Oracle are for the
hybrid setups documented in `DEPLOYMENT_HYBRID.md` / `DEPLOYMENT_ORACLE.md`, not needed here).

---

## Prerequisites

- Portainer CE installed and reachable on the NAS (Container Manager → Portainer, or
  the UGOS Docker app)
- The NAS has internet access to pull images from Docker Hub / build the app image
- At least ~6 GB free RAM and ~10 GB free disk (Postgres data + Ollama models +
  article cache grow over time)
- A VAPID keypair for push notifications (optional but recommended — see step 2)

---

## Step 1 — Create the stack from the Git repository

In Portainer:

1. **Stacks → Add stack**
2. Name it `dossier`
3. Build method: **Repository**
   - Repository URL: `https://github.com/etorhub/dossier`
   - Repository reference: `refs/heads/master`
   - Compose path: leave the default (`docker-compose.yml`) — Portainer only loads
     one path, so we'll supply the NAS overrides as environment variables instead
     (see the note at the end of Step 3)

> **Simplest alternative — Web editor:** if you'd rather not wire up Git polling,
> choose build method **Web editor**, then paste the **merged** result of
> `docker compose -f docker-compose.yml -f docker-compose.nas.yml config`
> (run that command once from a checkout, e.g. on your dev machine, and paste the
> output). This gives Portainer a single self-contained compose file with the NAS
> tuning already baked in — no extra `-f` flags needed.

---

## Step 2 — Environment variables

In the stack's **Environment variables** section, add (Portainer → "Add an
environment variable", or paste as `.env` if using the web editor):

```bash
# Required
POSTGRES_PASSWORD=<choose-a-strong-password>
SECRET_KEY=<generate-with: python3 -c "import secrets; print(secrets.token_hex(32))">

# Ollama runs in this stack
COMPOSE_PROFILES=local-llm
OLLAMA_HOST=http://ollama:11434

# Push notifications — generate once:
#   python3 -c "from pywebpush import Vapid; v = Vapid(); v.generate_keys(); \
#     print('VAPID_PUBLIC_KEY=' + v.public_key.decode()); \
#     print('VAPID_PRIVATE_KEY=' + v.private_key.decode())"
VAPID_PUBLIC_KEY=<paste>
VAPID_PRIVATE_KEY=<paste>
VAPID_EMAIL=mailto:etorius@gmail.com
```

Never commit these to the repo — they live only in the Portainer stack's environment.

---

## Step 3 — Apply the NAS overrides

The NAS override (`docker-compose.nas.yml`) does three things, all aimed at keeping
the stack lightweight on shared hardware:

- Strips the GPU reservation from `ollama` (CPU-only inference)
- Sets `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=1` (one model resident
  at a time — the daily job only ever needs `qwen2.5:3b` or `bge-m3`, never both
  simultaneously)
- Skips pulling `qwen2.5:7b` in `ollama-init` (the NAS profile only uses `qwen2.5:3b`
  — this saves ~5 GB of download/disk versus the default compose)

If you used the **Repository** build method, Portainer can't merge two compose files
directly — use the **web editor** instead and paste the merged config as described in
Step 1 (`docker compose ... config` output). This is the recommended path: it's a
single source of truth for what's actually running, and it's easy to diff against the
repo when you update.

---

## Step 4 — Deploy and watch the first start

Click **Deploy the stack**. On first start:

1. `db` comes up and passes its healthcheck
2. `db-init` runs Alembic migrations once, then exits (`service_completed_successfully`)
3. `ollama` starts (CPU mode — no GPU device requests)
4. `ollama-init` pulls `qwen2.5:3b` and `bge-m3` (~2–3 GB total) — this is the slowest
   step on first run, expect 10–30 minutes depending on NAS bandwidth/disk speed —
   then exits
5. `web`, `worker`, and `ops` start once their dependencies are healthy/complete

Watch progress in Portainer: **Stacks → dossier → Containers**, check logs on
`ollama-init` for pull progress, and on `worker` for `"waiting for ollama-init"` →
`"scheduler started"`.

---

## Step 5 — First-run setup

Once `web` is healthy:

1. Open `http://<nas-ip>:5000`, create the admin account, and complete the setup
   wizard (topics, sources, rewrite tone)
2. Open the ops dashboard at `http://<nas-ip>:5001` to confirm feed health and job runs
3. Trigger an initial fetch so the app has content immediately instead of waiting for
   the next scheduled run:

   ```bash
   docker exec -it <worker-container-name> ./scripts/fetch-news.sh
   ```

   (or run it from a checkout pointed at the NAS's published Postgres/Ollama ports)

The daily pipeline then runs unattended: fetch → enrich → embed → cluster
continuously, and the 06:00 job selects the top 10 stories, rewrites them in
Catalan, and sends the push notification.

---

## Performance tuning for the DSP 2800

The NAS override already applies the safe defaults below. Adjust only if you observe
resource pressure (Portainer → container stats, or the NAS's own resource monitor):

| Setting | Default (NAS profile) | When to change |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | Raise to `2` only if RAM ≥ 16 GB and rewrites feel slow |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Keep at `1` — embedding and rewriting never run concurrently in the daily job |
| `SCHEDULER_MODE` | `full` | Keep at `full` for a single-machine deployment (don't split light/heavy on one box) |
| gunicorn workers (`web`) | default (compose doesn't pin `-w`) | If RAM is tight, add `-w 1` to the `web` command, mirroring `docker-compose.pi.yml` |

General guidance:
- `qwen2.5:3b` is the right model for 10 stories/day on CPU — don't switch to `7b`
  on this hardware; it roughly doubles inference time and RAM for marginal quality gain
- Postgres, Ollama, and the article/job-run data all persist in named volumes/bind
  mounts — back up `pgdata`, `ollama_data`, and `./data/job_runs` before any major
  Portainer stack recreation
- If the NAS also runs other containers (Plex, etc.), consider setting per-service
  memory limits in the compose (`mem_limit:`) so Dossier can't starve them during the
  06:00 rewrite burst

---

## Updating the stack

With the **Repository** build method, Portainer can poll the `master` branch and
redeploy automatically (enable "Automatic updates" / webhook on the stack). With the
**web editor** method, you'll need to re-paste the merged compose when the base files
change — check `docker-compose.yml` / `docker-compose.nas.yml` for updates and re-run
`docker compose ... config` to regenerate.

Either way, `db-init` re-runs Alembic migrations safely on every redeploy (idempotent),
and `ollama-init` only pulls models that aren't already in the `ollama_data` volume.

---

## Troubleshooting

- **`ollama-init` stuck / failing to pull**: check NAS internet connectivity and disk
  space (`docker system df`); model pulls need ~5 GB free during download+extraction
- **`worker` logs `waiting for ollama-init`**: normal on first start — wait for the
  pull to finish; subsequent restarts skip this since models persist in `ollama_data`
- **Web UI slow on first open**: the worker hasn't completed its first pipeline pass
  yet — run `./scripts/fetch-news.sh` manually (Step 5) to seed content immediately
- **Out of memory**: lower `OLLAMA_NUM_PARALLEL`/`OLLAMA_MAX_LOADED_MODELS` further
  (already at the minimum `1`), add `-w 1` to gunicorn, or check for other containers
  competing for RAM during the 06:00 rewrite window
