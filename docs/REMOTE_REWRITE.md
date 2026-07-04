# Running the LLM pipeline stages off-host against the NAS's production database

The NAS (Postgres + web + ops + worker) is the single source of truth, deployed as
described in [`docs/DEPLOYMENT_PORTAINER.md`](DEPLOYMENT_PORTAINER.md). It runs **no
Ollama** and its worker runs "light" — fetch, enrich, and availability only. The
LLM stages that turn fetched articles into the daily digest — **embed + cluster →
rewrite → highlight** — run off-host on GPU compute and write results back into the
NAS's Postgres. This is not optional: without it, the NAS has articles but no digest.

The primary runner is **Modal (free tier, on-demand GPU)** — see
[`deploy/modal/`](../deploy/modal/). Any machine with `cloudflared` + `docker` works
too (local GPU box, an ad-hoc server, a VPS) via `scripts/run-remote-pipeline.sh`.
On GPU you get the full-quality `qwen2.5:14b` (the default config), no CPU model.

Running the stages never double-processes: each stage only touches work still
pending (e.g. `run_rewrite_batch` skips stories that already have a rewrite), so a
same-day rerun is a no-op. Every run is recorded in `job_runs`
(`trigger` + `origin_hostname`/`origin_ip`), visible on the ops dashboard.

## One-time setup

### 1. Create the restricted database role

Migrations `037_pipeline_remote_role.py` and `038_pipeline_llm_stages_role.py` create
and scope a `dossier_pipeline` role to exactly the tables the LLM stages touch:
`articles` (read + write only the `embedding`/`embedding_vec` columns), `stories` and
`story_articles` (create/update memberships + centroids), `story_rewrites` (rewrites +
highlights), and `job_runs` (tracking). It has **no** access to `users` or any other
table, cannot insert articles or change sources, and is a different role from the
`dossier` role the app itself uses.

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

### 3. Choose a runner

**Primary — Modal (recommended).** On-demand GPU, `modal.Cron` schedule, idles at
$0 within free-tier credits. Full setup (secrets, deploy) is in
[`deploy/modal/README.md`](../deploy/modal/README.md). In short:

```bash
modal secret create dossier-cf-access \
  CF_DB_HOSTNAME=db.<your-domain> \
  CF_ACCESS_CLIENT_ID=<service token id> \
  CF_ACCESS_CLIENT_SECRET=<service token secret>
modal secret create dossier-db DOSSIER_PIPELINE_PASSWORD=<the password from step 1>
modal deploy deploy/modal/dossier_llm.py   # installs the 06:00 UTC schedule
```

**Alternative — any box with `cloudflared` + `docker`** (local GPU, ad-hoc, VPS).
Nothing else to install — the job runs inside the published
`ghcr.io/etorhub/dossier-worker` image:

```bash
export CF_DB_HOSTNAME=db.<your-domain>
export CF_ACCESS_CLIENT_ID=<service token id>
export CF_ACCESS_CLIENT_SECRET=<service token secret>
export DOSSIER_PIPELINE_PASSWORD=<the password from step 1>
export OLLAMA_HOST=http://host.docker.internal:11434  # wherever Ollama runs on this machine

./scripts/run-remote-pipeline.sh
```

The script opens a local proxy to the NAS's Postgres via `cloudflared access tcp`,
waits for it to be ready, runs `python -m app.worker_cli run-llm-stages` (embed +
cluster → rewrite → highlight) inside the published worker image against that proxy,
and tears the proxy down when done. Whatever `OLLAMA_HOST` points at is where the
actual LLM inference happens. To run it on a schedule, put the script + env vars on
a cron entry there — ordinary ops on that box, not a Dossier feature.

## Verifying

- `job_runs` on the ops dashboard (`http://<nas-ip>:5001`) shows a new row **per
  stage** (`cluster_articles`, `rewrite_articles`, `highlight_stories`) with
  `trigger = manual` and `origin_hostname`/`origin_ip` matching the runner, right
  after it completes.
- The NAS worker's own rows keep showing only the non-LLM jobs (`fetch_feeds`,
  `enrich_articles`, `check_source_availability`) with `origin_mode = light`.
- To confirm the role really is scoped correctly, try something outside its grants
  (e.g. `SELECT * FROM users` or `DROP TABLE stories`) with `psql` using the
  `dossier_pipeline` credentials through the same tunnel proxy — both should fail
  with a permissions error.
