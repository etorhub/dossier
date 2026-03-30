# Deployment: Oracle Cloud Always Free (heavy worker)

This guide sets up the **heavy pipeline worker** on an Oracle Cloud Always Free A1 instance
(ARM Ampere, 4 OCPU, 24 GB RAM). It runs alongside the Pi (light worker + web UI) and
shares the same Neon PostgreSQL database.

---

## Architecture overview

```
Neon PostgreSQL (cloud)
        │
        ├── Raspberry Pi  (docker-compose.pi.yml)
        │     web UI + SCHEDULER_MODE=light
        │     fetch feeds, enrich, source availability
        │
        └── Oracle A1     (docker-compose.heavy.yml + docker-compose.cpu.yml)
              SCHEDULER_MODE=heavy
              cluster, embed, rewrite, highlight
              Ollama (CPU — qwen2.5:7b, qwen2.5:3b, bge-m3)
```

Pi and Oracle connect only to Neon — never to each other directly.
Oracle needs **no inbound ports** beyond SSH.

---

## Prerequisites

- Neon database already provisioned; you have the connection string:
  `postgresql://user:pass@ep-xxx.neon.tech/dossier?sslmode=require`
- Pi (or equivalent) running the light worker and web UI
- GitHub account with read access to `ghcr.io/etorhub/dossier` packages
  (or the package visibility set to public in GHCR settings)
- Oracle Cloud account (free tier is sufficient)

---

## 1. Create the Oracle A1 instance

### 1.1 Sign up / log in

Go to [cloud.oracle.com](https://cloud.oracle.com) and sign in. Always Free resources
never expire and require no payment method beyond initial verification.

### 1.2 Launch a compute instance

1. **Compute → Instances → Create instance**
2. **Name:** `dossier-heavy` (or any name)
3. **Image:** Canonical Ubuntu 22.04 (or 24.04) — choose the ARM64 variant
4. **Shape:** `VM.Standard.A1.Flex`
   - OCPUs: **4** (maximum free)
   - Memory: **24 GB** (maximum free)
5. **Boot volume:** increase to **50 GB** (default is 47 GB; models alone need ~8 GB)
6. **SSH keys:** upload your public key (`~/.ssh/id_rsa.pub` or generate a new one)
7. Click **Create**

The instance will be ready in ~2 minutes. Note the **public IP address**.

### 1.3 Add a block volume for Ollama models (recommended)

Models persist across container restarts in the `ollama_data` Docker volume, but
keeping them on a dedicated block volume avoids filling the boot disk.

1. **Storage → Block Volumes → Create Block Volume**
   - Name: `dossier-ollama`
   - Size: **50 GB** (free tier allows up to 200 GB total)
   - Same availability domain as the instance
2. **Attach** to the instance (Compute → Instances → dossier-heavy → Attached block volumes)
   - Access type: **Read/Write**, device path: `/dev/oracleoci/oraclevdb`
3. On the instance, format and mount:

```bash
sudo mkfs.ext4 /dev/sdb          # or /dev/oracleoci/oraclevdb — confirm with lsblk
sudo mkdir -p /mnt/ollama-data
sudo mount /dev/sdb /mnt/ollama-data
echo '/dev/sdb /mnt/ollama-data ext4 defaults,_netdev 0 2' | sudo tee -a /etc/fstab
```

If you skip this step, models will be stored inside the boot volume — it still works
but monitor disk usage with `df -h`.

---

## 2. Configure networking

Oracle wraps instances in a **Virtual Cloud Network (VCN)** with its own security list.
By default, only port 22 (SSH) is open inbound — that is all the heavy worker needs.

Verify in **Networking → Virtual Cloud Networks → [your VCN] → Security Lists:**

| Direction | Protocol | Source / Destination | Port | Purpose |
|-----------|----------|---------------------|------|---------|
| Ingress   | TCP      | 0.0.0.0/0           | 22   | SSH     |
| Egress    | All      | 0.0.0.0/0           | All  | Outbound (Neon, RSS, GHCR, Docker Hub) |

Do **not** open port 5432, 11434, or 5001. The worker only makes outbound connections.

---

## 3. Prepare the server

SSH into the instance:

```bash
ssh ubuntu@<oracle-public-ip>
```

### 3.1 System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates
```

### 3.2 Docker Engine

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker          # apply group change in this session
```

Verify:

```bash
docker run --rm hello-world
```

### 3.3 docker compose plugin

Docker's modern `compose` plugin is included with the `get.docker.com` script.
Confirm:

```bash
docker compose version
# Docker Compose version v2.x.x
```

---

## 4. Clone the repository

```bash
cd /opt
sudo git clone https://github.com/etorhub/dossier.git dossier
sudo chown -R ubuntu:ubuntu dossier
cd dossier
```

Pull the same branch/tag that the Pi is running to keep config in sync:

```bash
git checkout master
```

---

## 5. Authenticate with GHCR

The worker image is published to GitHub Container Registry. If the package is private
you need to log in with a Personal Access Token (PAT):

1. [Create a PAT](https://github.com/settings/tokens/new) with **`read:packages`** scope
2. On the Oracle instance:

```bash
echo "<YOUR_PAT>" | docker login ghcr.io -u <your-github-username> --password-stdin
```

If the package is set to **public** in GHCR settings, skip this step.

---

## 6. Configure environment variables

```bash
cp .env.example .env
nano .env        # or vim / your preferred editor
```

Minimum required settings:

```bash
# External Neon database — same URL used by the Pi
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/dossier?sslmode=require

# Enable the bundled Ollama service
COMPOSE_PROFILES=local-llm

# Heavy jobs only: cluster, embed, rewrite, highlight
SCHEDULER_MODE=heavy
```

Remove or leave commented: `SECRET_KEY`, `POSTGRES_PASSWORD`, `VAPID_*`
(not needed — no web app runs here).

If you mounted a block volume for Ollama models, point the `ollama_data` Docker volume
at it by adding an override (see step 7.1).

---

## 7. Start the heavy stack

```bash
# GPU is stripped by the cpu override; Ollama runs in CPU mode
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml up -d
```

On **first boot**, `ollama-init` pulls three models before the worker starts:

| Model          | Size   | Purpose                  |
|----------------|--------|--------------------------|
| `qwen2.5:7b`   | ~4.7 GB | Neutral EN rewrite        |
| `qwen2.5:3b`   | ~2.0 GB | Simplify + translate      |
| `bge-m3`       | ~600 MB | Embeddings (clustering)   |

This takes **10–30 minutes** depending on Oracle's network. Watch progress:

```bash
docker logs -f dossier-ollama-init-1
# "ollama-init: done." signals completion
```

Models are cached in the `ollama_data` volume. Subsequent restarts skip the pull.

### 7.1 Optional: store Ollama models on the block volume

If you created a 50 GB block volume at `/mnt/ollama-data`, override the volume
mount before first boot:

```bash
cat > docker-compose.oracle-volumes.yml <<'EOF'
volumes:
  ollama_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/ollama-data
EOF

docker compose \
  -f docker-compose.heavy.yml \
  -f docker-compose.cpu.yml \
  -f docker-compose.oracle-volumes.yml \
  up -d
```

---

## 8. Verify the deployment

```bash
# 1. All services running
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml ps
# Expected: ollama (healthy), worker (running)

# 2. Worker logs — should see APScheduler registering heavy jobs
docker logs dossier-worker-1 | head -40

# 3. Manual end-to-end test
docker exec dossier-worker-1 python -m app.worker_cli run-pipeline
# Watch for "cluster_articles", "rewrite_articles", "highlight_stories" completing

# 4. Confirm stories appear as rewritten in the database
docker exec dossier-worker-1 python -m app.worker_cli embedding-status
```

---

## 9. CPU performance expectations

Oracle A1 Ampere is ARM64 with fast NEON SIMD — better than a typical x86 VPS for
inference. Rough benchmarks with default quantisation (Q4_K_M):

| Task                        | Approx time      |
|-----------------------------|------------------|
| bge-m3 embedding (1 article)| 2–5 s            |
| qwen2.5:3b rewrite          | 1–2 min/story    |
| qwen2.5:7b rewrite          | 3–6 min/story    |
| 20-story batch (3b, serial) | 20–40 min        |

For personal use (< 30 stories/day) this is comfortable. The pipeline runs every
30 minutes so a batch of 5–10 new stories is typical.

**Tuning knobs in `config/app.yaml`:**

```yaml
schedule:
  rewrite_batch_size: 10         # reduce from 20 for CPU (shorter runs, less memory)
  rewrite_parallel_workers: 1    # keep at 1 — CPU inference doesn't benefit from parallelism

llm:
  rewrite_model: qwen2.5:3b      # swap to 3b for 2–3× speed; slight quality trade-off
```

---

## 10. Auto-updates with Watchtower (optional)

CI builds a new `:worker` ARM64 image on every push to `master`. Watchtower can
redeploy it automatically, matching the Pi setup.

Add a `docker-compose.oracle-watchtower.yml` override:

```yaml
services:
  worker:
    labels:
      - com.centurylinklabs.watchtower.scope=dossier-oracle

  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ~/.docker:/config:ro
    environment:
      DOCKER_CONFIG: /config
      DOCKER_API_VERSION: '1.40'
      WATCHTOWER_POLL_INTERVAL: '60'
      WATCHTOWER_CLEANUP: 'true'
      WATCHTOWER_SCOPE: dossier-oracle
    command: --scope dossier-oracle
    restart: unless-stopped
```

Then start with:

```bash
docker compose \
  -f docker-compose.heavy.yml \
  -f docker-compose.cpu.yml \
  -f docker-compose.oracle-watchtower.yml \
  up -d
```

Watchtower polls GHCR every 60 seconds, pulls the new `:worker` image, and restarts
the worker container. No SSH needed for routine updates.

---

## 11. Useful commands

```bash
# Restart the stack
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml restart

# Stop cleanly
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml down

# View worker logs (last 100 lines, follow)
docker logs --tail=100 -f dossier-worker-1

# Run a single pipeline stage manually
docker exec dossier-worker-1 python -m app.worker_cli cluster-articles
docker exec dossier-worker-1 python -m app.worker_cli rewrite-articles

# Disk usage (monitor boot volume)
df -h /
du -sh /var/lib/docker/volumes/dossier_ollama_data

# Pull latest images without restarting
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml pull
docker compose -f docker-compose.heavy.yml -f docker-compose.cpu.yml up -d
```

---

## 12. Operations checklist

- [ ] Oracle A1 instance running (Ubuntu, ARM64, 4 OCPU, 24 GB RAM)
- [ ] Boot volume ≥ 50 GB (or block volume mounted for Ollama data)
- [ ] Security list: SSH (22) inbound only, all egress open
- [ ] Docker installed, `ubuntu` in `docker` group
- [ ] GHCR auth configured (or package is public)
- [ ] `.env` set: `DATABASE_URL`, `COMPOSE_PROFILES=local-llm`, `SCHEDULER_MODE=heavy`
- [ ] `ollama-init` completed model pulls (check logs)
- [ ] `docker compose ps` shows `worker` running
- [ ] Manual `run-pipeline` completes without errors
- [ ] Rewritten stories visible in the Pi web UI

---

## Reference

| File | Purpose |
|------|---------|
| `docker-compose.heavy.yml` | Heavy worker stack (GPU default) |
| `docker-compose.cpu.yml` | CPU override (strips GPU from Ollama) |
| `app/scheduler.py` | `SCHEDULER_MODE` job registration |
| `config/app.yaml` | `rewrite_batch_size`, `rewrite_parallel_workers` tuning |
| `docs/DEPLOYMENT_HYBRID.md` | Pi + local PC hybrid setup |
