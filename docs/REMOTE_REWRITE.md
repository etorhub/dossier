# Running the rewrite job remotely against the NAS's production database

The NAS (Postgres + web + ops + worker) is the single source of truth, deployed as
described in [`docs/DEPLOYMENT_PORTAINER.md`](DEPLOYMENT_PORTAINER.md). The worker's
internal scheduler keeps running the daily rewrite job at 06:00 there as a fallback.
This page covers the **optional, additional** path: running that same rewrite job
from your local machine (GPU) or an ad-hoc/VPS box, writing results into the NAS's
Postgres, when you want an earlier rewrite than the NAS's scheduled 06:00 job, or to run inference on a different machine (local GPU Ollama or Modal endpoints).

Running it externally never conflicts with the 06:00 job — `run_rewrite_batch` only
processes stories still needing a rewrite, so a same-day rerun after the scheduled
job is a no-op. Every run (scheduled or manual) is recorded in `job_runs`
(`trigger` + `origin_hostname`/`origin_ip`), visible on the ops dashboard.

## One-time setup

### 1. Create the restricted database role

Migration `037_pipeline_remote_role.py` creates a `dossier_pipeline` role scoped to
exactly the tables the rewrite job touches (`articles` read-only; `stories`,
`story_articles`, `story_rewrites`, `job_runs` per its actual read/write pattern) —
it does not have access to `users` or any other table, and it's a different role
from the `dossier` role the app itself uses.

The migration creates the role without a password. Set one manually, once, directly
on the NAS (never commit it, never put it in a migration):

```bash
docker exec -it <db-container-name> psql -U dossier -d dossier \
  -c "ALTER ROLE dossier_pipeline WITH PASSWORD '<generate a strong one>';"
```

Store that password in your password manager — you'll pass it to the wrapper script
as `DOSSIER_PIPELINE_PASSWORD`.

### 2. Expose Postgres through the Cloudflare Tunnel

`docker-compose.yml` publishes `db` on `127.0.0.1:5432` (loopback only — nothing
reachable from the LAN/WAN directly). On the NAS, add a TCP ingress rule to the
Cloudflare Tunnel config you already run there:

```yaml
ingress:
  - hostname: db.<your-domain>
    service: tcp://localhost:5432
  - service: http_status:404 # keep any existing catch-all last
```

Then, in Cloudflare Zero Trust → Access → Applications, add a **Self-hosted**
application on `db.<your-domain>` with a **Service Auth** policy, and issue a
service token per client machine (e.g. `local-machine`, `vps-worker`). Cloudflare
rejects connections without a valid token before they ever reach Postgres.

### 3. Install `cloudflared` and `docker` on the triggering machine

Whichever machine will run the job (your local box, an ad-hoc server, a VPS) needs
both installed. Nothing else — the job itself runs inside the already-published
`ghcr.io/etorhub/dossier-worker` image, so there's no repo checkout or Python
environment to set up there.

## Running it

```bash
export CF_DB_HOSTNAME=db.<your-domain>
export CF_ACCESS_CLIENT_ID=<service token id>
export CF_ACCESS_CLIENT_SECRET=<service token secret>
export DOSSIER_PIPELINE_PASSWORD=<the password from step 1>
export OLLAMA_HOST=http://host.docker.internal:11434  # wherever Ollama runs on this machine

./scripts/run-remote-rewrite.sh
```

The script opens a local proxy to the NAS's Postgres via `cloudflared access tcp`,
waits for it to be ready, runs `python -m app.worker_cli rewrite-articles` inside
the published worker image against that proxy, and tears the proxy down when done.
Inference runs wherever the worker container's provider env points: `OLLAMA_HOST` for local Ollama, or `LLM_PROVIDER=vllm` / `EMBED_PROVIDER=vllm` with Modal URLs (same vars as NAS prod). No Dossier code behaves differently based on where you invoke the script.

To trigger this from a VPS/ad-hoc server on its own schedule, put the same script
and env vars on a cron entry there — that's ordinary ops on that box, not a Dossier
feature.

## Verifying

- `job_runs` on the ops dashboard (`http://<nas-ip>:5001`) shows a new row with
  `trigger = manual` and `origin_hostname`/`origin_ip` matching the machine you ran
  it from, right after the script completes.
- The NAS's own 06:00 job is unaffected — its `job_runs` rows keep showing
  `trigger = scheduled`.
- To confirm the role really is scoped correctly, try something outside its grants
  (e.g. `SELECT * FROM users` or `DROP TABLE stories`) with `psql` using the
  `dossier_pipeline` credentials through the same tunnel proxy — both should fail
  with a permissions error.
