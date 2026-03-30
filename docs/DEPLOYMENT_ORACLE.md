# Deployment: Oracle Cloud Always Free

This guide deploys the full Dossier stack across **two Oracle Cloud Always Free instances**,
replacing both the Raspberry Pi and any local PC.

---

## Architecture

```
Neon PostgreSQL (external, cloud)
         │
         ├── Oracle A1 — light  (1 OCPU · 6 GB RAM · ARM64)
         │     Web UI (Flask · port 5000)
         │     Light worker: fetch feeds, enrich, source availability
         │     SCHEDULER_MODE=light
         │     docker-compose.pi.yml  ← same file as the Pi, same ARM64 images
         │
         └── Oracle A1 — heavy  (3 OCPU · 18 GB RAM · ARM64)
               Heavy worker: cluster, embed, rewrite, highlight
               Ollama CPU: qwen2.5:7b · qwen2.5:3b · bge-m3
               SCHEDULER_MODE=heavy
               docker-compose.heavy.yml + docker-compose.cpu.yml
```

The two instances share only the Neon database. They never communicate directly.
Neither instance needs inbound ports beyond SSH (and port 5000 for the web UI).

---

## Oracle Always Free quotas

Oracle gives every account a permanent free allocation of ARM Ampere resources:

| Resource | Free limit |
|----------|-----------|
| A1 Flex OCPU | 4 total across all A1 instances |
| A1 Flex RAM | 24 GB total across all A1 instances |
| Block storage | 200 GB total |
| Instances | Up to 4 |

Recommended split for Dossier:

| Instance | OCPU | RAM | Role |
|----------|------|-----|------|
| `dossier-light` | 1 | 6 GB | Web UI + light worker |
| `dossier-heavy` | 3 | 18 GB | Heavy worker + Ollama |
| **Total** | **4** | **24 GB** | ← exactly the free limit |

---

## Prerequisites

- Oracle Cloud account (free tier, always-free resources)
- Neon database provisioned; connection string ready:
  `postgresql://user:pass@ep-xxx.neon.tech/dossier?sslmode=require`
- GitHub account with access to `ghcr.io/etorhub/dossier` packages
  (or package visibility set to public in GHCR settings)
- A domain managed on Cloudflare (for the web tunnel — free plan is sufficient)
- SSH key pair (`ssh-keygen -t ed25519` if you don't have one)

---

## Part 1 — Light instance (web UI + light worker)

### 1.1 Create the instance

1. **Compute → Instances → Create instance**
2. Name: `dossier-light`
3. Image: **Canonical Ubuntu 24.04** — ARM-based (Ampere)
4. Shape: `VM.Standard.A1.Flex` — 1 OCPU, 6 GB RAM
5. Boot volume: **50 GB**
6. SSH key: paste your public key
7. Click **Create** — note the public IP

### 1.2 Security list

In **Networking → Virtual Cloud Networks → [VCN] → Security Lists**, confirm:

| Direction | Protocol | Port | Purpose |
|-----------|----------|------|---------|
| Ingress | TCP | 22 | SSH |
| Egress | All | All | Outbound (Neon, RSS, GHCR, Docker Hub) |

Do **not** open port 5000 publicly if you plan to use a Cloudflare Tunnel (recommended).

### 1.3 Server setup

SSH in and install Docker:

```bash
ssh ubuntu@<light-ip>

sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker
```

### 1.4 Authenticate with GHCR

`docker-compose.pi.yml` pulls pre-built images from GitHub Container Registry.

```bash
# Generate a PAT at github.com/settings/tokens with read:packages scope
echo "<YOUR_PAT>" | docker login ghcr.io -u <github-username> --password-stdin
```

Save credentials for Watchtower (it needs them too):

```bash
mkdir -p ~/.docker   # already exists after docker login
```

### 1.5 Clone and configure

```bash
cd /opt
sudo git clone https://github.com/etorhub/dossier.git dossier
sudo chown -R ubuntu:ubuntu dossier
cd dossier
```

```bash
cp .env.example .env
nano .env
```

Minimum `.env` for the light instance:

```bash
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/dossier?sslmode=require
SECRET_KEY=<strong-random-string>   # generate: python3 -c "import secrets; print(secrets.token_hex(32))"
GHCR_USERNAME=<github-username>
GHCR_TOKEN=<PAT with read:packages>
```

### 1.6 Start the light stack

```bash
docker compose -f docker-compose.pi.yml up -d
```

On first start, Watchtower and the app images are pulled from GHCR (~500 MB total).
The worker runs Alembic migrations automatically on the first boot if they haven't
run yet.

Check it's up:

```bash
docker compose -f docker-compose.pi.yml ps
docker logs dossier-web-1 --tail=30
```

You should see gunicorn accepting connections on port 5000.

### 1.7 Expose the web UI

**Option A — Cloudflare Tunnel (recommended, no open ports)**

Install `cloudflared` and create a tunnel:

```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
  https://pkg.cloudflare.com/cloudflared focal main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install -y cloudflared
```

Authenticate and create the tunnel (follow the URL in your browser):

```bash
cloudflared tunnel login
cloudflared tunnel create dossier
```

Configure `~/.cloudflared/config.yml`:

```yaml
tunnel: <your-tunnel-id>
credentials-file: /home/ubuntu/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: app.yourdomain.com
    service: http://localhost:5000
  - service: http_status:404
```

Add a DNS CNAME in the Cloudflare dashboard:
- Name: `app` → Target: `<tunnel-id>.cfargotunnel.com`

Run as a service:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

The app is now reachable at `https://app.yourdomain.com` with TLS, no open firewall port.

**Option B — Open port 5000 (simpler, less secure)**

Add an ingress rule to the Oracle security list: TCP port 5000 from `0.0.0.0/0`.
Also open it in the instance firewall:

```bash
sudo iptables -I INPUT -p tcp --dport 5000 -j ACCEPT
```

Access at `http://<light-ip>:5000`. Add a reverse proxy (nginx + Let's Encrypt)
for HTTPS if this will be used by real users.

---

## Part 2 — Heavy instance (heavy worker + Ollama)

### 2.1 Create the instance

1. **Compute → Instances → Create instance**
2. Name: `dossier-heavy`
3. Image: **Canonical Ubuntu 24.04** — ARM-based (Ampere)
4. Shape: `VM.Standard.A1.Flex` — 3 OCPU, 18 GB RAM
5. Boot volume: **50 GB** (models need ~8 GB; 50 GB leaves headroom for logs and updates)
6. SSH key: same as before
7. Click **Create** — note the public IP

### 2.2 Security list

Same as the light instance: **SSH (22) inbound only**. The heavy worker makes no
inbound connections — it only connects outbound to Neon (5432) and RSS feeds (443).

### 2.3 Server setup

```bash
ssh ubuntu@<heavy-ip>

sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker
```

### 2.4 Clone and configure

```bash
cd /opt
sudo git clone https://github.com/etorhub/dossier.git dossier
sudo chown -R ubuntu:ubuntu dossier
cd dossier
```

```bash
cp .env.example .env
nano .env
```

Minimum `.env` for the heavy instance:

```bash
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/dossier?sslmode=require
COMPOSE_PROFILES=local-llm
# SCHEDULER_MODE is set inside docker-compose.heavy.yml — no need to add it here
```

### 2.5 Start the heavy stack

```bash
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml up -d
```

The `docker-compose.cpu.yml` overlay strips the GPU reservation from Ollama.
Ollama runs in CPU mode on the Ampere cores.

On **first boot**, `ollama-init` pulls three models before the worker starts:

| Model | Compressed size | Purpose |
|-------|----------------|---------|
| `qwen2.5:7b` | ~4.7 GB | Neutral EN rewrite (merge sources) |
| `qwen2.5:3b` | ~2.0 GB | Simplify + translate |
| `bge-m3` | ~600 MB | Embeddings for clustering |

This takes **15–40 minutes** on first boot (depends on Oracle's network).
Watch progress:

```bash
docker logs -f dossier-ollama-init-1
# ends with: "ollama-init: done."
```

Models are cached in the `ollama_data` Docker volume and survive restarts.

Verify the worker is scheduling jobs:

```bash
docker logs dossier-worker-1 --tail=50
# Should show APScheduler registering: cluster_articles, rewrite_articles, highlight_stories
```

### 2.6 Manual end-to-end test

```bash
docker exec dossier-worker-1 python -m app.worker_cli run-pipeline
```

This runs all heavy stages sequentially. Check for errors and confirm rewritten
stories appear in the web UI.

---

## Performance expectations (CPU inference on Ampere A1)

ARM Ampere cores have efficient SIMD for matrix operations. With Q4_K_M quantisation:

| Task | Approx time |
|------|------------|
| `bge-m3` embedding (1 article) | 2–5 s |
| `qwen2.5:3b` rewrite | 1–2 min/story |
| `qwen2.5:7b` rewrite | 3–6 min/story |
| 10-story batch (7b, serial) | 30–60 min |

For personal use (< 30 new stories/day) this is comfortable — the rewrite job
runs every 30 minutes, so a typical batch is 3–8 new stories.

**Tuning in `config/app.yaml`:**

```yaml
schedule:
  rewrite_batch_size: 10        # reduce from 20 to keep individual runs short
  rewrite_parallel_workers: 1   # CPU inference gains nothing from parallelism

llm:
  rewrite_model: qwen2.5:3b     # optional: faster (1–2 min) at slight quality cost
```

---

## Auto-updates

### Light instance

Watchtower is already included in `docker-compose.pi.yml`. It polls GHCR every 60 seconds,
pulls a new `:web` or `:worker` image when CI pushes one, and restarts the affected container.
No action needed.

### Heavy instance

The heavy worker image is built locally (`build:` in `docker-compose.heavy.yml`).
To update it after a code change:

```bash
cd /opt/dossier
git pull origin main
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml build worker
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml up -d worker
```

Or automate with a cron job on the heavy instance:

```bash
crontab -e
# Add: 0 4 * * * cd /opt/dossier && git pull origin main && docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml up -d --build worker
```

---

## Keeping config in sync

Both instances use `config/app.yaml` from the cloned repo. After changing pipeline
settings (batch sizes, cron schedules, model names), pull on both instances:

```bash
# On both light and heavy:
cd /opt/dossier && git pull origin main
docker compose -f <the-relevant-compose-file> restart worker
```

---

## Operations checklist

**Oracle account**
- [ ] Two A1 Flex instances created (total ≤ 4 OCPU, 24 GB RAM)
- [ ] Security lists: SSH (22) inbound only on both instances

**Light instance (`dossier-light`)**
- [ ] Docker installed, `ubuntu` in `docker` group
- [ ] GHCR credentials saved (`docker login ghcr.io`)
- [ ] `.env` set: `DATABASE_URL`, `SECRET_KEY`, `GHCR_USERNAME`, `GHCR_TOKEN`
- [ ] `docker compose -f docker-compose.pi.yml ps` shows all services running
- [ ] Web UI reachable (via Cloudflare Tunnel or direct port)
- [ ] Watchtower running (auto-updates enabled)

**Heavy instance (`dossier-heavy`)**
- [ ] Docker installed, `ubuntu` in `docker` group
- [ ] `.env` set: `DATABASE_URL`, `COMPOSE_PROFILES=local-llm`
- [ ] `ollama-init` completed model pulls (check logs for "done.")
- [ ] `docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml ps` shows worker running
- [ ] Manual `run-pipeline` completes without errors
- [ ] Rewritten stories visible in the web UI

**End-to-end**
- [ ] Light worker fetching and enriching articles (check ops dashboard or worker logs)
- [ ] Heavy worker clustering and rewriting (check worker logs every 30 min)
- [ ] Stories appear in the feed within ~1 hour of being fetched

---

## Useful commands

```bash
# --- Light instance ---

# View web and worker logs
docker logs -f dossier-web-1
docker logs -f dossier-worker-1

# Restart everything
docker compose -f docker-compose.pi.yml restart

# Pull latest images manually (Watchtower does this automatically)
docker compose -f docker-compose.pi.yml pull && docker compose -f docker-compose.pi.yml up -d

# --- Heavy instance ---

# Watch worker scheduling output
docker logs --tail=100 -f dossier-worker-1

# Run a single stage manually
docker exec dossier-worker-1 python -m app.worker_cli cluster-articles
docker exec dossier-worker-1 python -m app.worker_cli rewrite-articles

# Check embedding queue
docker exec dossier-worker-1 python -m app.worker_cli embedding-status

# Monitor disk (boot volume — models live in Docker volume)
df -h /
docker system df
```

---

## Reference

| File | Purpose |
|------|---------|
| `docker-compose.pi.yml` | Light instance stack (web + light worker + Watchtower) |
| `docker-compose.heavy.yml` | Heavy instance stack (worker + Ollama, GPU default) |
| `docker-compose.cpu.yml` | CPU overlay — strips GPU reservation from Ollama |
| `config/app.yaml` | Pipeline tuning (`rewrite_batch_size`, `rewrite_parallel_workers`) |
| `docs/DEPLOYMENT_HYBRID.md` | Raspberry Pi + local PC setup |
| `app/scheduler.py` | `SCHEDULER_MODE` job registration |
