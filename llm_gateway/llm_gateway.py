"""
llm_gateway.py

Nadie debería llamar a Ollama directamente salvo este servicio. Su único
trabajo es controlar CUÁNTAS peticiones concurrentes llegan al LLM
(con un semáforo) para no saturarlo cuando varios workers o el backend
piden generar texto a la vez.

Puerto: 8091
Arrancar: python3 llm_gateway/llm_gateway.py
"""

import os
import threading
import time

import requests
from flask import Flask, request, jsonify

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "2"))

app = Flask(__name__)
_semaphore = threading.Semaphore(MAX_CONCURRENT)
_stats_lock = threading.Lock()
_stats = {"in_flight": 0, "total_requests": 0, "total_rejected_timeout": 0}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ready")
def ready():
    """Comprueba que Ollama de verdad responde, no solo que este proceso vive."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        ok = r.status_code == 200
    except requests.RequestException:
        ok = False
    return jsonify({"ready": ok}), (200 if ok else 503)


@app.route("/metrics")
def metrics():
    with _stats_lock:
        return jsonify({
            **_stats,
            "max_concurrent": MAX_CONCURRENT,
            "slots_free": MAX_CONCURRENT - _stats["in_flight"],
        })


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(force=True) or {}
    prompt = payload.get("prompt", "")

    acquired = _semaphore.acquire(timeout=30)
    if not acquired:
        with _stats_lock:
            _stats["total_rejected_timeout"] += 1
        return jsonify({"error": "LLM saturado, reintenta más tarde"}), 503

    with _stats_lock:
        _stats["in_flight"] += 1
        _stats["total_requests"] += 1
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": payload.get("model", "llama3.1"), "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    finally:
        with _stats_lock:
            _stats["in_flight"] -= 1
        _semaphore.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8091)
