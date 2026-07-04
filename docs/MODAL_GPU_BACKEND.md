# Modal GPU Backend

LLM inference for Dossier runs on **Modal** — two independent, scale-to-zero GPU
functions reached over HTTPS. The NAS app stack (db, web, worker, ops) is unchanged;
the worker calls these endpoints for every embed and rewrite operation.

---

## Architecture

```
NAS worker (APScheduler)
  │
  ├─ embed job (hourly) ──► HTTPS ──► dossier-embed   [BGE-M3, L4 GPU]   ─► vectors
  └─ rewrite job (06:00) ─► HTTPS ──► dossier-rewrite [Qwen2.5-32B, L40S] ─► Catalan text
```

Both apps expose an **OpenAI-compatible** REST API (`/v1/embeddings`,
`/v1/chat/completions`) served by vLLM. The worker uses the existing
`VllmOpenAIProvider` / `VllmOpenAIEmbeddingProvider` classes — no new client code.
Auth is a bearer token validated by vLLM's built-in `--api-key` flag.

---

## Models and GPUs

| Function | Model | GPU | VRAM | Est. cost |
|---|---|---|---|---|
| Rewrite + proofread | `Qwen/Qwen2.5-32B-Instruct-AWQ` | L40S (48 GB) | ~20 GB | ~$10–15/month |
| Embeddings | `BAAI/bge-m3` | L4 (24 GB) | ~2 GB | ~$1–2/month |

**Why these choices:**

- **Qwen2.5-32B-AWQ** — large enough to produce correct Catalan without the
  Spanish-leakage retries that plagued `qwen2.5:3b`. AWQ 4-bit quantisation keeps VRAM
  well within L40S capacity while preserving output quality. The daily volume (~20
  rewrite+proofread calls) means the GPU runs for roughly 10–15 minutes/day — cost is
  dominated by cold-start overhead, not token throughput.
- **BGE-M3** — restores the embedding quality that was downgraded in Alembic migration
  `034` for CPU-speed reasons. On GPU it embeds in milliseconds; the cross-lingual
  Catalan/Spanish same-event clustering score is noticeably better than
  `paraphrase-multilingual`.
- **L40S** — cheapest GPU with 48 GB VRAM, enough for the 32B AWQ model plus a
  generous KV-cache budget for the ~52 KB merged-source inputs.
- **L4** — cheapest GPU with enough VRAM for BGE-M3; more than adequate for a
  sub-1-second embedding call.

Both apps use `scaledown_window` scale-to-zero — they spin down after a period of
inactivity and cold-start on the next call. Expect a 30–90 s delay on the first
call of the day (model weights load from the Modal Volume cache into GPU memory).
Subsequent calls in the same session are fast.

---

## One-time setup

### 1. Install Modal CLI

```bash
pip install modal
modal setup     # authenticates your Modal account
```

### 2. Create secrets

Each Modal app uses a secret to hold the bearer token the worker sends.
Generate two random tokens and store them:

```bash
# Rewrite app token
modal secret create dossier-rewrite-key \
  DOSSIER_REWRITE_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Embed app token
modal secret create dossier-embed-key \
  DOSSIER_EMBED_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

> Keep these tokens — you'll paste them into the NAS `.env` / Portainer stack
> environment as `OPENAI_API_KEY` and `EMBED_API_KEY`.

### 3. Deploy the apps

```bash
# From the repo root:
modal deploy modal/rewrite_server.py
modal deploy modal/embed_server.py
```

Each deploy prints a URL like:
```
https://<workspace>--dossier-rewrite-serve.modal.run
```

Note both URLs — you'll need the `/v1` suffixed form for the env vars.

### 4. Smoke-test the endpoints

```bash
# Test rewrite endpoint
curl -s https://<workspace>--dossier-rewrite-serve.modal.run/v1/chat/completions \
  -H "Authorization: Bearer <rewrite-token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-32B-Instruct-AWQ","messages":[{"role":"user","content":"Hola"}],"max_tokens":10}' \
  | python3 -m json.tool

# Test embed endpoint
curl -s https://<workspace>--dossier-embed-serve.modal.run/v1/embeddings \
  -H "Authorization: Bearer <embed-token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"BAAI/bge-m3","input":"test"}' \
  | python3 -m json.tool
```

Both should return valid JSON with a `choices` / `data` array respectively. The
first call after a cold-start may take up to 90 s — that's normal.

---

## NAS configuration

In the Portainer stack environment (or the NAS `.env`), set:

```bash
LLM_PROVIDER=vllm
LLM_API_BASE=https://<workspace>--dossier-rewrite-serve.modal.run/v1
OPENAI_API_KEY=<rewrite-token>

EMBED_PROVIDER=vllm
EMBED_API_BASE=https://<workspace>--dossier-embed-serve.modal.run/v1
EMBED_API_KEY=<embed-token>
```

Remove or leave unset `COMPOSE_PROFILES` and `OLLAMA_HOST` — the Ollama containers
are not needed on the NAS when Modal is active.

---

## Local development

Local dev keeps using Ollama (`COMPOSE_PROFILES=local-llm` in `.env`). Leave
`LLM_PROVIDER` / `EMBED_PROVIDER` unset — the provider factory defaults to `ollama`.
No Modal account is required to run or test the app locally.

If you want to test against the live Modal endpoints locally, set the env vars in your
local `.env` exactly as above. Be aware this incurs Modal GPU costs.

---

## Redeploying after model or config changes

```bash
modal deploy modal/rewrite_server.py   # picks up any changes to rewrite_server.py
modal deploy modal/embed_server.py
```

Model weights are cached in a Modal Volume (`dossier-hf-cache`). Changing the model
name in the server file will trigger a new download on the next cold start (~15–30 min
for a 20 GB AWQ model — subsequent cold starts use the cached weights).

---

## Monitoring and costs

- **Modal dashboard** → Apps → `dossier-rewrite` / `dossier-embed`: call logs,
  latency, GPU utilisation, and per-day cost breakdown.
- **Ops dashboard** (`http://<nas-ip>:5001`) → Jobs: rewrite job duration and error
  rate. A spike in duration usually means a Modal cold start coincided with the 06:00
  job — normal once per day.
- To pause billing entirely (e.g. while travelling): `modal app stop dossier-rewrite`
  and `modal app stop dossier-embed`. Redeploy when you want the digest to run again.
