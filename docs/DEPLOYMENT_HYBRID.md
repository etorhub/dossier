# Hybrid deployment: Raspberry Pi + PC

This guide describes running **PostgreSQL, the web app, and light pipeline jobs** on a **Raspberry Pi 3B+** (or similar), while **Ollama and heavy jobs** (embeddings, clustering, rewrites) run on a **local PC** on the same LAN. The PC connects to the Pi’s database over the network.

For the default all-in-one setup, use Docker as described in [TECH_STACK.md](TECH_STACK.md).

---

## Architecture

| Machine | Role | `SCHEDULER_MODE` | Software |
|--------|------|------------------|----------|
| **Raspberry Pi** | Postgres, Flask (readers), fetch / enrich / availability | `light` | `requirements-pi.txt` |
| **PC** | Embeddings, clustering, LLM rewrites | `heavy` | `requirements.txt` (includes `ollama`) |

Environment variables:

- **Pi:** `DATABASE_URL` → local Postgres, `SCHEDULER_MODE=light`, `SECRET_KEY`.
- **PC:** `DATABASE_URL` → `postgresql://dossier:PASSWORD@PI_LAN_IP:5432/dossier`, `OLLAMA_HOST=http://localhost:11434`, `SCHEDULER_MODE=heavy`.

Both hosts need the same `config/` directory (or deploy the repo on both). Run **Alembic migrations once** (on the Pi, against the Pi database) before starting either scheduler.

---

## 1. Raspberry Pi preparation

### 1.1 Base system

- Use **Raspberry Pi OS Lite** (64-bit if available) to save RAM.
- Prefer **native installs** (no Docker on the Pi) — Docker adds noticeable overhead on 1 GB RAM.

### 1.2 PostgreSQL

Install PostgreSQL 18 (or the version your distro ships; align with project expectations).

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

Create role and database (adjust password):

```bash
sudo -u postgres psql -c "CREATE USER dossier WITH PASSWORD 'your-secure-password';"
sudo -u postgres psql -c "CREATE DATABASE dossier OWNER dossier;"
```

**Listen on the LAN** so the PC can connect. Edit `postgresql.conf` (location varies, e.g. `/etc/postgresql/18/main/postgresql.conf`):

```ini
listen_addresses = '*'
```

Restrict who can reach port 5432 with a host firewall (e.g. `ufw allow from 192.168.1.0/24 to any port 5432`) so Postgres is not open to the whole internet.

Edit `pg_hba.conf` (same directory) and allow the PC subnet:

```text
host    dossier    dossier    192.168.1.0/24    scram-sha-256
```

Adjust the CIDR to your LAN. Reload Postgres: `sudo systemctl reload postgresql`.

**Memory tuning** (important on 1 GB RAM). In `postgresql.conf`:

```ini
shared_buffers = 128MB
effective_cache_size = 384MB
work_mem = 4MB
maintenance_work_mem = 64MB
max_connections = 20
```

Restart PostgreSQL after changes.

### 1.3 Python application

Install Python 3.12+ if available (`sudo apt install python3 python3-venv python3-pip build-essential libpq-dev`).

```bash
cd /opt   # or your preferred path
sudo git clone https://github.com/etorhub/dossier.git dossier
sudo chown -R $USER:$USER dossier
cd dossier
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-pi.txt
```

Copy `.env.example` to `.env` and set at least:

```bash
DATABASE_URL=postgresql://dossier:your-secure-password@127.0.0.1:5432/dossier
SECRET_KEY=<long-random-string>
SCHEDULER_MODE=light
```

Run migrations and seed sources (from the repo root, venv active):

```bash
export FLASK_APP=app:create_app
alembic upgrade head
flask seed-sources
```

### 1.4 Gunicorn (web app)

Bind to all interfaces if the tunnel runs on the same host (or keep `127.0.0.1` if only `cloudflared` connects locally):

```bash
gunicorn -b 0.0.0.0:5000 --workers 2 app:application
```

Use a **systemd** unit for production, e.g. `/etc/systemd/system/dossier-web.service`:

```ini
[Unit]
Description=Dossier web
After=network.target postgresql.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/opt/dossier
EnvironmentFile=/opt/dossier/.env
ExecStart=/opt/dossier/.venv/bin/gunicorn -b 127.0.0.1:5000 --workers 2 app:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Using `127.0.0.1` limits direct exposure; pair with a tunnel (below).

### 1.5 Light scheduler (systemd)

`/etc/systemd/system/dossier-scheduler-light.service`:

```ini
[Unit]
Description=Dossier light scheduler
After=network.target postgresql.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/opt/dossier
EnvironmentFile=/opt/dossier/.env
ExecStart=/opt/dossier/.venv/bin/python -m app.scheduler
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Ensure `.env` includes `SCHEDULER_MODE=light`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dossier-web.service dossier-scheduler-light.service
```

### 1.6 Ops dashboard (optional)

Runs on the Pi for operators. Second Gunicorn process on port 5001:

```bash
/opt/dossier/.venv/bin/gunicorn -b 127.0.0.1:5001 --workers 1 ops:application
```

Add a systemd unit similar to `dossier-web.service` with `ops:application` and port `5001`.

**If using `docker-compose.pi.yml`**, the ops service is included automatically — no extra systemd unit needed.

Do **not** expose port 5001 publicly without authentication. See section 1.7 for how to expose it safely via Cloudflare Access.

### 1.7 Exposing services to the internet

Pick one:

**A. Cloudflare Tunnel (recommended)**
Install `cloudflared` on the Pi, create a Named Tunnel in the Cloudflare dashboard, and configure `~/.cloudflared/config.yml` with two ingress rules:

```yaml
tunnel: <your-tunnel-id>
credentials-file: /home/pi/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: app.yourdomain.com
    service: http://localhost:5000
  - hostname: ops.yourdomain.com
    service: http://localhost:5001
  - service: http_status:404
```

Add DNS CNAME records for both hostnames pointing to `<tunnel-id>.cfargotunnel.com`.

Restart after editing: `sudo systemctl restart cloudflared`

**Protecting the ops dashboard with Cloudflare Access**
The ops dashboard has no built-in authentication. Restrict it to your email via Cloudflare Zero Trust:

1. Go to **Zero Trust → Access → Applications → Add an application**
2. Type: **Self-hosted**; Application domain: `ops.yourdomain.com`
3. Create a policy: **Allow** → email is `your@email.com`
4. Save

Unauthenticated visitors hitting `ops.yourdomain.com` see a Cloudflare login page and cannot proceed. The web app at `app.yourdomain.com` remains public.

**B. Tailscale Funnel**
Install Tailscale on the Pi, enable Funnel, publish the web service. Simpler DNS (`*.ts.net`) but different operational trade-offs (bandwidth, branding). Note: ops dashboard would only be reachable within the Tailnet — not via Funnel — unless explicitly configured.

Do not rely on port-forwarding without TLS and a clear security review.

---

## 2. PC (heavy worker + Ollama)

### 2.1 Ollama

Install [Ollama](https://ollama.com/) and pull models (defaults match [config/app.yaml](../config/app.yaml)):

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
ollama pull bge-m3
```

Ensure `ollama serve` is running (often as a system service).

### 2.2 Application and scheduler

Clone the same repo revision as the Pi (or sync `config/`). Create a venv and install **full** worker dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For production you may omit dev-only packages at the bottom of `requirements.txt` if you prefer a slimmer install.

`.env` on the PC:

```bash
DATABASE_URL=postgresql://dossier:your-secure-password@PI_LAN_IP:5432/dossier
OLLAMA_HOST=http://127.0.0.1:11434
SCHEDULER_MODE=heavy
```

Use the Pi’s **LAN IP** (static DHCP reservation recommended).

### 2.3 Run heavy scheduler

```bash
cd /path/to/dossier
source .venv/bin/activate
python -m app.scheduler
```

Use systemd (Linux), a launch agent (macOS), or Task Scheduler (Windows) so the heavy worker starts on login/boot.

**Note:** If the PC is off, clustering and rewrites do not run; the Pi still fetches and enriches. Content already rewritten remains visible. When the PC returns, the next scheduled cluster/rewrite jobs catch up.

---

## 3. Polling intervals

Light jobs on the Pi use [config/app.yaml](../config/app.yaml) (`schedule.fetch_interval_minutes`, `enrichment_cron`, etc.). For fetches every 5–10 minutes, lower `fetch_interval_minutes` and align cron expressions; deploy the same `config/` on both hosts.

---

## 4. Operations checklist

- [ ] Pi: Postgres listening, `pg_hba` allows PC subnet, password matches `.env` on both sides.
- [ ] Pi: `alembic upgrade head` and `flask seed-sources` completed once.
- [ ] Pi: `SCHEDULER_MODE=light`, web + light scheduler running.
- [ ] PC: Ollama models pulled, `SCHEDULER_MODE=heavy`, `DATABASE_URL` points at Pi.
- [ ] Firewall on Pi: only necessary ports open (often none if using a tunnel to localhost:5000).

---

## 5. Moving the heavy worker to a VPS later

Point `DATABASE_URL` on the VPS to the Pi’s **public** Postgres endpoint only if you expose Postgres securely (TLS, allowlist, strong auth) — **not** recommended without a VPN or tunnel. Safer patterns:

- Move Postgres to the VPS and run heavy worker there with Ollama on the same VPS; or  
- Keep DB on the Pi and connect the VPS to the home network via **Tailscale** or **WireGuard**, then use the Pi’s tailnet IP in `DATABASE_URL`.

---

## 6. Reference

| File | Purpose |
|------|---------|
| [app/scheduler.py](../app/scheduler.py) | `SCHEDULER_MODE` and job registration |
| [requirements-pi.txt](../requirements-pi.txt) | Pi dependencies (no `ollama`) |
| [.env.example](../.env.example) | Environment variable template |

Invalid `SCHEDULER_MODE` values fall back to `full` (all jobs), matching Docker behaviour when the variable is unset.
