"""Modal app: run Dossier's off-host LLM pipeline stages on a schedule.

This is the primary runner for the LLM half of the pipeline (embed+cluster →
rewrite → highlight). The NAS runs "light" (fetch/enrich/availability only, no
Ollama); this Modal function connects to the NAS's Postgres over a Cloudflare
Tunnel, runs Ollama on an on-demand GPU, and produces the daily digest.

Because it runs on a GPU, it uses the default full-quality model (qwen2.5:14b) —
no DOSSIER_LLM_MODEL override needed. The container idles at $0 between runs.

Setup (once), see deploy/modal/README.md:
  modal secret create dossier-cf-access \\
    CF_DB_HOSTNAME=db.<your-domain> \\
    CF_ACCESS_CLIENT_ID=<service token id> \\
    CF_ACCESS_CLIENT_SECRET=<service token secret>
  modal secret create dossier-db DOSSIER_PIPELINE_PASSWORD=<role password>
  modal deploy deploy/modal/dossier_llm.py     # installs the 06:00 UTC schedule

Run manually (dry run against prod, outside the schedule):
  modal run deploy/modal/dossier_llm.py
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable

import modal

# Reuse the already-published worker image (public GHCR, contains the app code),
# then layer in cloudflared + ollama so everything runs in one container.
WORKER_TAG = os.environ.get("DOSSIER_TAG", "latest")
OLLAMA_MODELS_DIR = "/root/.ollama"

image = (
    modal.Image.from_registry(
        f"ghcr.io/etorhub/dossier-worker:{WORKER_TAG}",
        add_python="3.12",
    )
    .apt_install("curl", "ca-certificates")
    .run_commands(
        # cloudflared (Cloudflare Tunnel client, for the Postgres TCP route)
        "curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64 -o /usr/local/bin/cloudflared",
        "chmod +x /usr/local/bin/cloudflared",
        # ollama (local inference server)
        "curl -fsSL https://ollama.com/install.sh | sh",
    )
)

# Persist pulled models across runs so we pull qwen2.5:14b + bge-m3 only once.
models_volume = modal.Volume.from_name("dossier-ollama-models", create_if_missing=True)

app = modal.App("dossier-llm")


def _run_llm_stages() -> None:
    """Start ollama + the tunnel proxy, then run the three LLM stages."""
    # 1. Ollama server + models (bge-m3 for embeddings, qwen2.5:14b for rewrite).
    subprocess.Popen(["ollama", "serve"])
    _wait_for("http://localhost:11434", "ollama", _ollama_ready)
    for model in ("bge-m3", "qwen2.5:14b"):
        print(f"Ensuring model present: {model}")
        subprocess.run(["ollama", "pull", model], check=True)
    models_volume.commit()

    # 2. Cloudflare Tunnel proxy to the NAS's loopback-only Postgres.
    tunnel = subprocess.Popen(
        [
            "cloudflared",
            "access",
            "tcp",
            "--hostname",
            os.environ["CF_DB_HOSTNAME"],
            "--url",
            "127.0.0.1:5432",
            "--service-token-id",
            os.environ["CF_ACCESS_CLIENT_ID"],
            "--service-token-secret",
            os.environ["CF_ACCESS_CLIENT_SECRET"],
        ]
    )
    try:
        _wait_for("127.0.0.1:5432", "tunnel", _pg_port_open)

        # 3. Run embed+cluster → rewrite → highlight against the NAS DB.
        password = os.environ["DOSSIER_PIPELINE_PASSWORD"]
        env = {
            **os.environ,
            "DATABASE_URL": (
                f"postgresql://dossier_pipeline:{password}@127.0.0.1:5432/dossier"
            ),
            "OLLAMA_HOST": "http://localhost:11434",
        }
        subprocess.run(
            ["python", "-m", "app.worker_cli", "run-llm-stages"],
            check=True,
            env=env,
            cwd="/app",
        )
    finally:
        tunnel.terminate()


def _ollama_ready() -> bool:
    return subprocess.run(["ollama", "list"], capture_output=True).returncode == 0


def _pg_port_open() -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", 5432)) == 0


def _wait_for(what: str, name: str, ready: Callable[[], bool], timeout: float = 120) -> None:
    print(f"Waiting for {name} ({what})...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ready():
            print(f"{name} ready.")
            return
        time.sleep(1.0)
    raise TimeoutError(f"{name} not ready within {timeout}s")


# Daily at 06:00 UTC — matches the pipeline's rewrite_cron. GPU is only billed
# while the function runs (a few minutes/day), so this stays inside free-tier credits.
@app.function(
    image=image,
    gpu="T4",
    timeout=60 * 30,
    volumes={OLLAMA_MODELS_DIR: models_volume},
    secrets=[
        modal.Secret.from_name("dossier-cf-access"),
        modal.Secret.from_name("dossier-db"),
    ],
    schedule=modal.Cron("0 6 * * *"),
)
def run_daily() -> None:
    _run_llm_stages()


@app.local_entrypoint()
def main() -> None:
    """`modal run deploy/modal/dossier_llm.py` — one-off invoke against prod."""
    run_daily.remote()
