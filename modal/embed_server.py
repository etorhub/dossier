# Deploy: modal deploy modal/embed_server.py
# See docs/MODAL_GPU_BACKEND.md

import subprocess

import modal

app = modal.App("dossier-embed")

MODEL_NAME = "BAAI/bge-m3"
HF_CACHE = modal.Volume.from_name("dossier-hf-cache", create_if_missing=True)
VLLM_CACHE = modal.Volume.from_name("dossier-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install("vllm==0.21.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)

MINUTES = 60
VLLM_PORT = 8000


@app.function(
    image=image,
    gpu="L4",
    scaledown_window=20 * MINUTES,
    timeout=15 * MINUTES,
    secrets=[modal.Secret.from_name("dossier-embed-key")],
    volumes={
        "/root/.cache/huggingface": HF_CACHE,
        "/root/.cache/vllm": VLLM_CACHE,
    },
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=VLLM_PORT, startup_timeout=15 * MINUTES)
def serve() -> None:
    import os

    api_key = os.environ.get("DOSSIER_EMBED_API_KEY", "")
    cmd = [
        "vllm",
        "serve",
        MODEL_NAME,
        "--runner",
        "pooling",
        "--served-model-name",
        MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--enforce-eager",
    ]
    if api_key:
        cmd += ["--api-key", api_key]
    subprocess.Popen(cmd)
