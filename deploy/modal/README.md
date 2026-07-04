# Modal runner — off-host LLM pipeline stages

The NAS runs Dossier "light": it fetches feeds and enriches full text, but runs
**no Ollama** and none of the LLM stages. This Modal app runs those stages
(embed+cluster → rewrite → highlight) once a day on an on-demand GPU, writing
results back into the NAS's Postgres over a Cloudflare Tunnel. It's the primary
daily digest producer; `scripts/run-remote-pipeline.sh` is the equivalent
local/VPS path.

Because it runs on a GPU, it uses the full-quality `qwen2.5:14b` (the default
config) — better rewrites than the old CPU model, and the container is billed
only while it runs (a few minutes/day), so it stays inside Modal's free-tier
credits and idles at $0.

## Prerequisites

1. The NAS is deployed with the light worker (`DOSSIER_LLM_JOBS_ENABLED=false`) —
   see [`docs/DEPLOYMENT_PORTAINER.md`](../../docs/DEPLOYMENT_PORTAINER.md).
2. The one-time remote-access setup from
   [`docs/REMOTE_REWRITE.md`](../../docs/REMOTE_REWRITE.md) is done:
   - `dossier_pipeline` role password set on the NAS (migrations `037` + `038`).
   - Cloudflare Tunnel TCP ingress rule for `db.<your-domain> → tcp://localhost:5432`.
   - A Cloudflare Access service token for this Modal client.
3. `pip install modal` and `modal setup` (authenticate the CLI) locally.

## One-time setup

Create the two secrets Modal injects into the function:

```bash
modal secret create dossier-cf-access \
  CF_DB_HOSTNAME=db.<your-domain> \
  CF_ACCESS_CLIENT_ID=<service token id> \
  CF_ACCESS_CLIENT_SECRET=<service token secret>

modal secret create dossier-db \
  DOSSIER_PIPELINE_PASSWORD=<the dossier_pipeline role password>
```

## Deploy the daily schedule

```bash
modal deploy deploy/modal/dossier_llm.py
```

This installs the `modal.Cron("0 6 * * *")` schedule (06:00 UTC). The first run
pulls `bge-m3` + `qwen2.5:14b` into a persistent Modal Volume
(`dossier-ollama-models`); later runs reuse it.

## Run manually (dry run against prod)

```bash
modal run deploy/modal/dossier_llm.py
```

Verify on the ops dashboard (`http://<nas-ip>:5001`): a new `job_runs` row per
stage (`cluster_articles`, `rewrite_articles`, `highlight_stories`) with
`trigger = manual` and an `origin_hostname` from the Modal container. The NAS
worker's own rows keep showing only the non-LLM jobs.

## Notes

- Pin the worker image with `DOSSIER_TAG=v1.2.0 modal deploy …` for reproducible
  runs (defaults to `latest`).
- Change the schedule by editing `modal.Cron(...)` in `dossier_llm.py` and
  redeploying. Note the cron is UTC; adjust for your local 06:00.
- Running Modal never conflicts with anything on the NAS: `run_rewrite_batch` only
  touches stories still needing a rewrite, so a re-run the same day is a no-op.
